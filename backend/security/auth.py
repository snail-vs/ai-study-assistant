import base64
import hashlib
import hmac
import os
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuthSession, InviteCode, User

SESSION_COOKIE = "studycenter_session"
_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session_days() -> int:
    return max(1, int(os.getenv("STUDYCENTER_SESSION_DAYS", "30")))


def _secure_cookie() -> bool:
    return os.getenv("STUDYCENTER_COOKIE_SECURE", "false").lower() == "true"


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            expires_at=datetime.utcnow() + timedelta(days=_session_days()),
        )
    )
    return token


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=_session_days() * 86400,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.expires_at > datetime.utcnow(),
        )
    )
    if not session:
        return None
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        return None
    session.last_seen_at = datetime.utcnow()
    _current_user_id.set(user.id)
    return user


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def current_user_id() -> str:
    value = _current_user_id.get()
    if not value:
        raise RuntimeError("current user is not available")
    return value


def consume_invite(db: Session, code: str) -> InviteCode | None:
    code_hash = hashlib.sha256(code.strip().encode()).hexdigest()
    invite = db.scalar(
        select(InviteCode).where(
            InviteCode.code_hash == code_hash,
            InviteCode.used_count < InviteCode.max_uses,
        )
    )
    if invite and invite.expires_at and invite.expires_at <= datetime.utcnow():
        return None
    return invite
