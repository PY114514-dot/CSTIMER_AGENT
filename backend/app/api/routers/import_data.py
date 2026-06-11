"""
Import Router: cstimer JSON 导入
"""
from __future__ import annotations
import json
import os
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.api.schemas import ImportResp
from app.persistence.cstimer_importer import import_from_file
from app.persistence.db import SessionLocal
from app.persistence.models import Cube


router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/cstimer", response_model=ImportResp)
async def import_cstimer(
    file: UploadFile = File(...),
    username: str = Form("imported"),
):
    """接收 cstimer 导出的 JSON 文件, 导入到 DB"""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(400, "expected a .json file")

    # 写到临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb") as f:
        content = await file.read()
        f.write(content)
        tmp_path = f.name

    try:
        sessions = import_from_file(tmp_path, username=username)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(500, f"import failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 统计 cubes
    cubes_count = 0
    with SessionLocal() as s:
        for sess in sessions:
            cubes_count += sess.cube_count or 0

    return ImportResp(
        sessions_imported=len(sessions),
        cubes_imported=cubes_count,
        session_ids=[sess.id for sess in sessions],
    )
