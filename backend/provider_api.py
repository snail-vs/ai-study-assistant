"""Authenticated provider settings and ChatGPT OAuth endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai.oauth_chatgpt import (
    create_browser_authorization,
    exchange_authorization_code,
    parse_authorization_input,
    poll_device_authorization,
    start_device_authorization,
)
from .ai.registry import CHATGPT_PROVIDER, create_named_text_provider
from .ai.tasks import TASKS
from .db import get_db
from .models import DefaultModelPreference, ProviderCredential
from .schemas import (
    ChatGptLoginCompleteRequest,
    ChatGptLoginRequest,
    ChatGptLoginResponse,
    ChatGptLoginStatusRequest,
    ChatGptLoginStatusResponse,
    ConfigureProviderRequest,
    ConfigureTaskRoutesRequest,
    DiscoverModelsRequest,
    DiscoverModelsResponse,
    ProviderSettingsResponse,
    SelectModelRequest,
    TaskRouteResponse,
)
from .security.auth import current_user_id, require_current_user
from .security.encryption import EncryptionError, decrypt_secret, encrypt_secret
from .services.provider_settings import (
    SUPPORTED_PROVIDER_NAMES,
    chatgpt_credential,
    persist_chatgpt_token,
    provider_settings,
    restore_active_provider,
    save_task_routes,
)
from .services.chatgpt_oauth import (
    chatgpt_login_sessions,
    complete_login,
    login_status,
    logout,
    refresh_chatgpt_models,
    run_chatgpt_device_login as _run_chatgpt_device_login,
    save_chatgpt_login,
    start_login,
)


async def run_chatgpt_device_login(session_id: str, device, user_id: str) -> None:
    return await _run_chatgpt_device_login(
        session_id,
        device,
        user_id,
        poller=poll_device_authorization,
        saver=save_chatgpt_login,
        model_refresher=refresh_chatgpt_models,
    )

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.get("/settings/providers", response_model=ProviderSettingsResponse)
def get_provider_settings(db: Session = Depends(get_db)):
    restore_active_provider(db)
    return provider_settings(db)


@router.post("/settings/providers/{provider_name}/models", response_model=DiscoverModelsResponse)
async def discover_models(
    provider_name: str,
    payload: DiscoverModelsRequest,
    db: Session = Depends(get_db),
):
    if provider_name == CHATGPT_PROVIDER:
        credential = db.get(ProviderCredential, (current_user_id(), CHATGPT_PROVIDER))
        if credential is None or credential.auth_type != "oauth":
            raise HTTPException(status_code=400, detail="请先完成 ChatGPT 设备码登录")
        try:
            provider = create_named_text_provider(
                provider_name, "", oauth=chatgpt_credential(credential)
            )
            models = await provider.list_models()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"models": models}
    api_key = payload.api_key
    if not api_key:
        credential = db.get(ProviderCredential, (current_user_id(), provider_name))
        if not credential:
            raise HTTPException(status_code=400, detail="Provider is not configured")
        try:
            api_key = decrypt_secret(credential.api_key_ciphertext, credential.api_key_nonce)
        except EncryptionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        provider = create_named_text_provider(provider_name, api_key)
        models = await provider.list_models()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not models:
        raise HTTPException(status_code=502, detail="Provider returned an empty model list")
    return {"models": models}


@router.put("/settings/providers/{provider_name}", response_model=ProviderSettingsResponse)
def configure_provider(
    provider_name: str,
    payload: ConfigureProviderRequest,
    db: Session = Depends(get_db),
):
    user_id = current_user_id()
    models = list(dict.fromkeys(payload.models))
    if payload.default_model is not None and payload.default_model not in models:
        raise HTTPException(
            status_code=400, detail="Default model must be one of the selected models"
        )
    credential = db.get(ProviderCredential, (user_id, provider_name))
    ciphertext: str | None = None
    nonce: str | None = None
    if provider_name == CHATGPT_PROVIDER:
        if credential is None or credential.auth_type != "oauth":
            raise HTTPException(status_code=400, detail="请先完成 ChatGPT 设备码登录")
        try:
            create_named_text_provider(
                provider_name, "", payload.default_model, oauth=chatgpt_credential(credential),
                on_token_refresh=lambda token: persist_chatgpt_token(user_id, token),
            )
        except (ValueError, EncryptionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        api_key = payload.api_key
        if not api_key:
            if credential is None:
                raise HTTPException(
                    status_code=400, detail="API Key is required for a new provider"
                )
            try:
                api_key = decrypt_secret(credential.api_key_ciphertext, credential.api_key_nonce)
            except EncryptionError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        try:
            if payload.api_key:
                ciphertext, nonce = encrypt_secret(api_key)
            create_named_text_provider(provider_name, api_key, payload.default_model)
        except (ValueError, EncryptionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if credential is None:
        credential = ProviderCredential(user_id=user_id, provider_name=provider_name)
        db.add(credential)
    if ciphertext is not None:
        credential.api_key_ciphertext = ciphertext
        credential.api_key_nonce = nonce or ""
    credential.models_json = json.dumps(models)
    if credential.active_model is None and models:
        credential.active_model = models[0]
    if payload.task_routes is not None:
        db.flush()
        save_task_routes(payload.task_routes, db)
    credential.is_active = True
    for other in db.scalars(
        select(ProviderCredential).where(
            ProviderCredential.user_id == user_id,
            ProviderCredential.provider_name != provider_name,
        )
    ):
        other.is_active = False
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.put("/settings/model", response_model=ProviderSettingsResponse)
def select_model(payload: SelectModelRequest, db: Session = Depends(get_db)):
    user_id = current_user_id()
    preference = db.scalar(
        select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id)
    )
    active_credential = (
        db.get(ProviderCredential, (user_id, preference.provider_name))
        if preference
        else None
    )
    if active_credential is None:
        active_credential = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.is_active.is_(True),
            )
        )
    active = active_credential.provider_name if active_credential else "mock"
    provider_name, separator, model_id = payload.model.partition(":")
    if separator:
        active = provider_name
        active_credential = db.get(ProviderCredential, (user_id, provider_name))
    else:
        model_id = payload.model
    selected_models = json.loads(active_credential.models_json or "[]") if active_credential else []
    if active == "mock" or model_id not in selected_models:
        raise HTTPException(
            status_code=400, detail="Model is not available for the active provider"
        )
    next_id = (
        (db.scalar(select(func.max(DefaultModelPreference.id))) or 0) + 1
        if preference is None
        else preference.id
    )
    preference = preference or DefaultModelPreference(id=next_id, user_id=user_id)
    preference.provider_name = active
    preference.model_id = model_id
    db.add(preference)
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.get("/settings/model-routes", response_model=list[TaskRouteResponse])
def get_model_routes(db: Session = Depends(get_db)):
    routes = provider_settings(db)["taskRoutes"]
    return [
        {
            "id": task.id,
            "label": task.label,
            "category": task.category,
            "model": routes.get(task.id),
        }
        for task in TASKS
    ]


@router.put("/settings/model-routes", response_model=ProviderSettingsResponse)
def configure_model_routes(payload: ConfigureTaskRoutesRequest, db: Session = Depends(get_db)):
    active = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.user_id == current_user_id(),
            ProviderCredential.is_active.is_(True),
        )
    )
    if not active:
        raise HTTPException(status_code=400, detail="请先配置一个 AI Provider")
    save_task_routes(payload.routes, db)
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.delete("/settings/providers/{provider_name}", response_model=ProviderSettingsResponse)
def clear_provider(provider_name: str, db: Session = Depends(get_db)):
    if provider_name not in SUPPORTED_PROVIDER_NAMES:
        raise HTTPException(status_code=404, detail="Provider not found")
    user_id = current_user_id()
    credential = db.get(ProviderCredential, (user_id, provider_name))
    if credential:
        db.delete(credential)
    preference = db.scalar(
        select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id)
    )
    if preference and preference.provider_name == provider_name:
        db.delete(preference)
    db.commit()
    return provider_settings(db)


@router.post("/settings/providers/chatgpt/oauth/login", response_model=ChatGptLoginResponse)
async def chatgpt_oauth_login(payload: ChatGptLoginRequest):
    return await start_login(
        payload.method,
        current_user_id(),
        browser_authorizer=create_browser_authorization,
        device_authorizer=start_device_authorization,
        device_runner=run_chatgpt_device_login,
    )


@router.post("/settings/providers/chatgpt/oauth/status", response_model=ChatGptLoginStatusResponse)
def chatgpt_oauth_status(payload: ChatGptLoginStatusRequest, db: Session = Depends(get_db)):
    return login_status(payload.session_id, db, provider_restorer=restore_active_provider)


@router.post(
    "/settings/providers/chatgpt/oauth/complete",
    response_model=ChatGptLoginStatusResponse,
)
async def chatgpt_oauth_complete(
    payload: ChatGptLoginCompleteRequest,
    db: Session = Depends(get_db),
):
    return await complete_login(
        payload.session_id,
        payload.input,
        db,
        input_parser=parse_authorization_input,
        code_exchanger=exchange_authorization_code,
        saver=save_chatgpt_login,
        model_refresher=refresh_chatgpt_models,
        provider_restorer=restore_active_provider,
    )


@router.post("/settings/providers/chatgpt/oauth/logout", response_model=ProviderSettingsResponse)
def chatgpt_oauth_logout(db: Session = Depends(get_db)):
    return logout(
        db,
        current_user_id(),
        provider_restorer=restore_active_provider,
        settings_reader=provider_settings,
    )
