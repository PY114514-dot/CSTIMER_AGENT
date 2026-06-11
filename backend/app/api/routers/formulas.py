"""
Formula Library Router
  GET  /api/formulas/sets                   -> 全部 set 列表
  GET  /api/formulas/sets/{code}            -> 单 set + 全部 cases/algs
  GET  /api/formulas/cases/{case_id}        -> 单 case
  GET  /api/formulas/search?q=...&set=...  -> 模糊查 case
  POST /api/formulas/seed                   -> 手动触发 seed (admin 用)
"""
from __future__ import annotations
import logging
import os
import time
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    FormulaSetSummary, FormulaSetDetail, FormulaCaseResp, FormulaAlgResp,
)
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import FormulaSet, FormulaCase
from app.persistence.formula_importer import (
    import_all, import_one_set, DEFAULT_FILES, FormulaFetchError, SOURCE_TAG,
)

logger = logging.getLogger("cstimer-coach.formulas")
router = APIRouter(prefix="/api/formulas", tags=["formulas"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _cache_dir() -> str:
    """每次请求读 env, 方便测试时动态切换"""
    return os.environ.get("FORMULA_CACHE_DIR", "data/formulas_cache")


def _set_summary(fs: FormulaSet) -> FormulaSetSummary:
    return FormulaSetSummary(
        id=fs.id, code=fs.code, puzzle=fs.puzzle, display_name=fs.display_name,
        case_count=fs.case_count, source=fs.source, fetched_at=fs.fetched_at,
    )


def _case_resp(c: FormulaCase) -> FormulaCaseResp:
    return FormulaCaseResp(
        id=c.id, name=c.name, code=c.code, recognition=c.recognition,
        mirror_of=c.mirror_of, position_in_set=c.position_in_set,
        is_symmetric=c.is_symmetric,
        algs=[FormulaAlgResp(
            id=a.id, seq=a.seq, alg_text=a.alg_text, fingertricks=a.fingertricks,
            move_count=a.move_count, is_canonical=a.is_canonical, notes=a.notes,
        ) for a in c.algs],
    )


@router.get("/sets", response_model=list[FormulaSetSummary])
def list_sets(db: Session = Depends(_get_db)):
    return [_set_summary(fs) for fs in repo.list_formula_sets(db)]


@router.get("/sets/{code}", response_model=FormulaSetDetail)
def get_set(code: str, db: Session = Depends(_get_db)):
    fs = repo.get_formula_set_with_cases(db, code)
    if not fs:
        raise HTTPException(404, f"formula set '{code}' not found (run POST /api/formulas/seed first)")
    return FormulaSetDetail(
        **_set_summary(fs).model_dump(),
        cases=[_case_resp(c) for c in fs.cases],
    )


@router.get("/cases/{case_id}", response_model=FormulaCaseResp)
def get_case(case_id: int, db: Session = Depends(_get_db)):
    c = repo.get_formula_case(db, case_id)
    if not c:
        raise HTTPException(404, f"case {case_id} not found")
    return _case_resp(c)


@router.get("/search", response_model=list[FormulaCaseResp])
def search(q: str = Query("", description="match case name/code (lowercase contains)"),
           set: str | None = Query(None, description="restrict to set code e.g. PLL"),
           limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(_get_db)):
    cases = repo.search_formula_cases(db, q, set_code=set, limit=limit)
    return [_case_resp(c) for c in cases]


@router.post("/seed", response_model=list[dict])
def seed(only: str | None = Query(None, description="seed only this set code, e.g. PLL"),
         use_cache: bool = Query(True, description="reuse data/formulas_cache/*.json if exists"),
         cache_dir: str | None = Query(None, description="override cache dir (test/internal)"),
         db: Session = Depends(_get_db)):
    """拉取上游 JSON + upsert 到 DB. 无网络时若有缓存仍可走 cache"""
    effective_cache = cache_dir if cache_dir is not None else (_cache_dir() if use_cache else None)
    if only:
        file = next((f for f in DEFAULT_FILES if f[1] == only), None)
        if not file:
            raise HTTPException(400, f"unknown set code '{only}'")
        try:
            res = [import_one_set(db, filename=file[0], set_code=file[1], display_name=file[2], cache_dir=effective_cache)]
        except FormulaFetchError as e:
            raise HTTPException(502, f"fetch failed: {e}")
    else:
        try:
            res = import_all(db, cache_dir=effective_cache)
        except FormulaFetchError as e:
            raise HTTPException(502, f"fetch failed: {e}")
    db.commit()
    logger.info(f"seed done: {res}")
    return res
