"""ChatGPT OAuth session and credential workflows."""

import asyncio
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.oauth_chatgpt import (
    BROWSER_REDIRECT_URI,
    ChatGptCredential,
    ChatGptOAuthError,
    create_browser_authorization,
    exchange_authorization_code,
    parse_authorization_input,
    poll_device_authorization,
    start_device_authorization,
)
from ..ai.providers.chatgpt import CODEX_MODELS, DEFAULT_CODEX_MODEL
from ..ai.registry import CHATGPT_PROVIDER, create_named_text_provider
from ..db import SessionLocal
from ..models import DefaultModelPreference, ProviderCredential
from ..security.auth import current_user_id
from .provider_settings import (
    apply_chatgpt_credential,
    provider_settings,
    restore_active_provider,
)

chatgpt_login_sessions: dict[str, dict] = {}


def save_chatgpt_login(user_id: str, credential: ChatGptCredential) -> None:
    db = SessionLocal()
    try:
        row = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
        if row is None:
            row = ProviderCredential(
                user_id=user_id,
                provider_name=CHATGPT_PROVIDER,
                api_key_ciphertext="",
                api_key_nonce="",
            )
            db.add(row)
        apply_chatgpt_credential(row, credential)
        selected = json.loads(row.models_json or "[]")
        if not selected:
            selected = list(CODEX_MODELS)
            row.models_json = json.dumps(selected)
        if row.active_model is None:
            row.active_model = selected[0] if selected else DEFAULT_CODEX_MODEL
        other_active = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.is_active.is_(True),
                ProviderCredential.provider_name != CHATGPT_PROVIDER,
            )
        )
        if other_active is None:
            row.is_active = True
        db.commit()
    finally:
        db.close()


async def refresh_chatgpt_models(user_id: str, credential: ChatGptCredential) -> None:
    try:
        provider = create_named_text_provider(CHATGPT_PROVIDER, "", oauth=credential)
        models = await provider.list_models()
    except Exception:  # noqa: BLE001
        return
    if not models:
        return
    db = SessionLocal()
    try:
        row = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
        if row is None:
            return
        row.models_json = json.dumps(models)
        if row.active_model not in models:
            row.active_model = models[0]
        db.commit()
    finally:
        db.close()


async def run_chatgpt_device_login(
    session_id: str,
    device,
    user_id: str,
    *,
    poller=None,
    saver=None,
    model_refresher=None,
) -> None:
    poller = poller or poll_device_authorization
    saver = saver or save_chatgpt_login
    model_refresher = model_refresher or refresh_chatgpt_models
    session = chatgpt_login_sessions.get(session_id)
    if session is None:
        return
    try:
        credential = await poller(device)
    except Exception as exc:  # noqa: BLE001
        session["status"], session["error"] = "failed", str(exc)
        return
    try:
        saver(user_id, credential)
    except Exception as exc:  # noqa: BLE001
        session["status"], session["error"] = "failed", f"凭证保存失败: {exc}"
        return
    await model_refresher(user_id, credential)
    session["status"], session["credential"] = "done", credential


async def start_login(
    method: str,
    user_id: str,
    *,
    browser_authorizer=None,
    device_authorizer=None,
    device_runner=None,
) -> dict:
    browser_authorizer = browser_authorizer or create_browser_authorization
    device_authorizer = device_authorizer or start_device_authorization
    device_runner = device_runner or run_chatgpt_device_login
    session_id = str(uuid4())
    if method == "browser":
        authorization = browser_authorizer()
        chatgpt_login_sessions[session_id] = {
            "method": "browser",
            "status": "pending",
            "credential": None,
            "error": None,
            "user_id": user_id,
            "verifier": authorization.verifier,
            "state": authorization.state,
        }
        return {"sessionId": session_id, "method": "browser", "authUrl": authorization.url}
    try:
        device = await device_authorizer()
    except ChatGptOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session = {
        "method": "device_code",
        "status": "pending",
        "credential": None,
        "error": None,
        "user_id": user_id,
    }
    chatgpt_login_sessions[session_id] = session
    session["task"] = asyncio.create_task(device_runner(session_id, device, user_id))
    return {
        "sessionId": session_id,
        "method": "device_code",
        "userCode": device.user_code,
        "verificationUri": device.verification_uri,
        "intervalSeconds": device.interval_seconds,
    }


def login_status(session_id: str, db: Session, *, provider_restorer=None) -> dict:
    provider_restorer = provider_restorer or restore_active_provider
    session = chatgpt_login_sessions.get(session_id)
    if session is None:
        return {"state": "unknown"}
    state = session.get("status")
    if state == "done":
        credential: ChatGptCredential = session["credential"]
        chatgpt_login_sessions.pop(session_id, None)
        provider_restorer(db, session["user_id"])
        return {
            "state": "done",
            "accountId": credential.account_id,
            "expires": credential.expires_at,
        }
    if state == "failed":
        error = session.get("error") or "登录失败"
        chatgpt_login_sessions.pop(session_id, None)
        return {"state": "failed", "error": error}
    return {"state": "pending"}


async def complete_login(
    session_id: str,
    value: str,
    db: Session,
    *,
    input_parser=None,
    code_exchanger=None,
    saver=None,
    model_refresher=None,
    provider_restorer=None,
) -> dict:
    input_parser = input_parser or parse_authorization_input
    code_exchanger = code_exchanger or exchange_authorization_code
    saver = saver or save_chatgpt_login
    model_refresher = model_refresher or refresh_chatgpt_models
    provider_restorer = provider_restorer or restore_active_provider
    session = chatgpt_login_sessions.get(session_id)
    if session is None:
        return {"state": "unknown"}
    if session.get("method") != "browser":
        raise HTTPException(status_code=400, detail="当前登录会话不是浏览器授权")
    try:
        code, state = input_parser(value)
        expected_state = session.get("state")
        if state and expected_state and state != expected_state:
            raise ChatGptOAuthError("state 校验失败，请重新发起登录")
        if not code:
            raise ChatGptOAuthError("未在输入中找到授权码")
        credential = await code_exchanger(
            code, session["verifier"], redirect_uri=BROWSER_REDIRECT_URI
        )
    except ChatGptOAuthError as exc:
        session["error"] = str(exc)
        return {"state": "failed", "error": str(exc)}
    try:
        user_id = session.get("user_id") or current_user_id()
        saver(user_id, credential)
    except Exception as exc:  # noqa: BLE001
        session["error"] = f"凭证保存失败: {exc}"
        return {"state": "failed", "error": session["error"]}
    await model_refresher(user_id, credential)
    chatgpt_login_sessions.pop(session_id, None)
    provider_restorer(db, user_id)
    return {"state": "done", "accountId": credential.account_id, "expires": credential.expires_at}


def logout(
    db: Session,
    user_id: str | None = None,
    *,
    user_id_getter=None,
    provider_restorer=None,
    settings_reader=None,
) -> dict:
    user_id_getter = user_id_getter or current_user_id
    provider_restorer = provider_restorer or restore_active_provider
    settings_reader = settings_reader or provider_settings
    user_id = user_id or user_id_getter()
    credential = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
    if credential is not None:
        db.delete(credential)
        preference = db.scalar(
            select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id)
        )
        if preference and preference.provider_name == CHATGPT_PROVIDER:
            db.delete(preference)
        db.commit()
    provider_restorer(db, user_id)
    return settings_reader(db)
