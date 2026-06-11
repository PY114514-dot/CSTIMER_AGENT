"""
Users Router: 用户管理
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import UserCreate, UserResp
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal


router = APIRouter(prefix="/api/users", tags=["users"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@router.post("", response_model=UserResp)
def create_user(req: UserCreate, db: Session = Depends(_get_db)):
    u = repo.get_or_create_user(
        db, req.username,
        display_name=req.display_name,
        timezone=req.timezone,
        avg_level=req.avg_level,
    )
    db.commit()
    return UserResp.model_validate(u)


@router.get("/{user_id}", response_model=UserResp)
def get_user(user_id: int, db: Session = Depends(_get_db)):
    u = db.get(__import__("app.persistence.models", fromlist=["User"]).User, user_id)
    if not u:
        raise HTTPException(404, f"user {user_id} not found")
    return UserResp.model_validate(u)


@router.get("/by-username/{username}", response_model=UserResp)
def get_user_by_name(username: str, db: Session = Depends(_get_db)):
    u = db.scalar(select(__import__("app.persistence.models", fromlist=["User"]).User)
                  .where(__import__("app.persistence.models", fromlist=["User"]).User.username == username))
    if not u:
        raise HTTPException(404, f"user {username} not found")
    return UserResp.model_validate(u)
