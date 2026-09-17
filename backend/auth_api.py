import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, DefaultModelPreference, InviteCode, LearningSpace, ProviderCredential, TaskModelRoute, User
from .schemas import AuthUserResponse, LoginRequest, RegisterRequest
from .security.auth import (
    SESSION_COOKIE,
    consume_invite,
    create_session,
    current_user_id,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
LEGACY_USER_ID = "00000000-0000-0000-0000-000000000001"


def user_response(user: User) -> dict:
    return {"id": user.id, "username": user.username}


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    invite = consume_invite(db, payload.invite_code)
    if not invite:
        raise HTTPException(status_code=400, detail="邀请码无效、已用完或已过期")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    # The first real account takes ownership of data created before auth was added.
    if db.scalar(select(func.count(User.id))) == 2:
        for model in (LearningSpace, ProviderCredential, TaskModelRoute, DefaultModelPreference):
            db.execute(update(model).where(model.user_id == LEGACY_USER_ID).values(user_id=user.id))
    invite.used_count += 1
    token = create_session(db, user)
    db.commit()
    set_session_cookie(response, token)
    return user_response(user)


@router.post("/login", response_model=AuthUserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_session(db, user)
    db.commit()
    set_session_cookie(response, token)
    return user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=AuthUserResponse)
def me(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user_response(user)
