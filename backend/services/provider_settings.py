"""Provider settings, credential persistence, and gateway restoration."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.gateway import AIGateway
from ..ai.base import AIProviderError
from ..ai.model_catalog import can_fall_back_to_manual, fetch_catalog
from ..ai.oauth_chatgpt import ChatGptCredential
from ..ai.providers.mock import MockTextProvider
from ..ai.registry import (
    CHATGPT_PROVIDER,
    PROVIDER_DEFINITIONS,
    create_named_text_provider,
)
from ..ai.tasks import TASK_BY_ID
from ..db import SessionLocal
from ..models import DefaultModelPreference, ProviderCredential, TaskModelRoute
from ..security.auth import current_user_id
from ..security.encryption import EncryptionError, decrypt_secret, encrypt_secret

SUPPORTED_PROVIDER_NAMES = (
    "deepseek",
    "google",
    "opencode",
    "openrouter",
    "anthropic",
    "glm",
    "zai",
    CHATGPT_PROVIDER,
)


async def discover_provider_models(provider_name: str, api_key: str) -> dict:
    """Resolve model candidates: dedicated URL, conventional URL, then manual entry."""
    definition = PROVIDER_DEFINITIONS.get(provider_name)
    if definition is None or provider_name == CHATGPT_PROVIDER:
        raise ValueError(f"Unsupported provider: {provider_name}")

    catalog_warning: str | None = None
    if definition.model_catalog is not None:
        try:
            return {
                "models": await fetch_catalog(definition.model_catalog, api_key),
                "source": "provider_catalog",
                "keyValidated": True,
            }
        except AIProviderError as exc:
            if not can_fall_back_to_manual(exc):
                raise
            catalog_warning = "Provider 专用模型目录不可用，已尝试通用模型目录。"

    try:
        provider = create_named_text_provider(provider_name, api_key)
        return {
            "models": await provider.list_models(),
            "source": "conventional",
            "warning": catalog_warning,
            "keyValidated": True,
        }
    except AIProviderError as exc:
        if not can_fall_back_to_manual(exc):
            raise
        return {
            "models": [],
            "source": "manual",
            "warning": "Provider 未提供可用的模型目录，请手动输入模型名称。",
            "keyValidated": False,
        }


def apply_chatgpt_credential(row: ProviderCredential, credential: ChatGptCredential) -> None:
    access_ciphertext, access_nonce = encrypt_secret(credential.access_token)
    refresh_ciphertext, refresh_nonce = encrypt_secret(credential.refresh_token)
    row.auth_type = "oauth"
    row.oauth_access_ciphertext = access_ciphertext
    row.oauth_access_nonce = access_nonce
    row.oauth_refresh_ciphertext = refresh_ciphertext
    row.oauth_refresh_nonce = refresh_nonce
    row.oauth_expires_at = credential.expires_at
    row.oauth_account_id = credential.account_id


def chatgpt_credential(row: ProviderCredential | None) -> ChatGptCredential | None:
    if (
        row is None
        or row.auth_type != "oauth"
        or not row.oauth_access_ciphertext
        or not row.oauth_refresh_ciphertext
        or not row.oauth_account_id
    ):
        return None
    try:
        return ChatGptCredential(
            access_token=decrypt_secret(row.oauth_access_ciphertext, row.oauth_access_nonce or ""),
            refresh_token=decrypt_secret(
                row.oauth_refresh_ciphertext, row.oauth_refresh_nonce or ""
            ),
            expires_at=row.oauth_expires_at or 0,
            account_id=row.oauth_account_id,
        )
    except EncryptionError:
        return None


def persist_chatgpt_token(user_id: str, credential: ChatGptCredential) -> None:
    db = SessionLocal()
    try:
        row = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
        if row is None:
            return
        apply_chatgpt_credential(row, credential)
        db.commit()
    finally:
        db.close()


def build_provider(provider_name: str, model: str | None, row: ProviderCredential | None):
    if provider_name == CHATGPT_PROVIDER:
        return create_named_text_provider(
            provider_name,
            "",
            model,
            oauth=chatgpt_credential(row),
            on_token_refresh=(
                lambda credential: persist_chatgpt_token(row.user_id, credential)
            )
            if row
            else None,
        )
    if row is None:
        raise ValueError(f"Provider is not configured: {provider_name}")
    api_key = decrypt_secret(row.api_key_ciphertext, row.api_key_nonce)
    return create_named_text_provider(provider_name, api_key, model)


def restore_active_provider(db: Session, user_id: str | None = None) -> AIGateway:
    user_id = user_id or current_user_id()
    preference = db.scalar(
        select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id)
    )
    credential = (
        db.get(ProviderCredential, (user_id, preference.provider_name))
        if preference
        else None
    )
    if credential is None:
        credential = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.is_active.is_(True),
            )
        )
    if not credential:
        return AIGateway(MockTextProvider())
    default_model = (
        preference.model_id
        if preference and preference.provider_name == credential.provider_name
        else credential.active_model
    )
    try:
        default_provider = build_provider(credential.provider_name, default_model, credential)
    except EncryptionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    task_providers = {}
    routes = list(db.scalars(select(TaskModelRoute).where(TaskModelRoute.user_id == user_id)))
    if not routes:
        routes = [
            TaskModelRoute(
                user_id=user_id,
                task=task,
                provider_name=credential.provider_name,
                model_id=model,
            )
            for task, model in json.loads(credential.task_routes_json or "{}").items()
        ]
    credentials = {
        item.provider_name: item
        for item in db.scalars(
            select(ProviderCredential).where(ProviderCredential.user_id == user_id)
        )
    }
    for route in routes:
        route_credential = credentials.get(route.provider_name)
        if route.task not in TASK_BY_ID or not route_credential:
            continue
        try:
            selected_models = json.loads(route_credential.models_json or "[]")
            if route.model_id in selected_models:
                task_provider = build_provider(
                    route.provider_name, route.model_id, route_credential
                )
                if route.task == "side_agent":
                    task_providers.setdefault("side_answer", task_provider)
                    task_providers.setdefault("gap_diagnosis", task_provider)
                elif route.task == "knowledge_card":
                    task_providers.setdefault("course_plan", task_provider)
                    task_providers.setdefault("section_content", task_provider)
                else:
                    task_providers[route.task] = task_provider
        except (EncryptionError, ValueError):
            continue
    user_gateway = AIGateway()
    user_gateway.configure(default_provider, task_providers)
    return user_gateway


def provider_settings(db: Session) -> dict:
    user_id = current_user_id()
    credentials = list(
        db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user_id))
    )
    providers = {name: False for name in SUPPORTED_PROVIDER_NAMES}
    models = {name: [] for name in SUPPORTED_PROVIDER_NAMES}
    preference = db.scalar(
        select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id)
    )
    active = db.get(ProviderCredential, (user_id, preference.provider_name)) if preference else None
    if active is None:
        active = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.is_active.is_(True),
            )
        )
    for credential in credentials:
        # Keep the persisted projection backward-compatible: configured provider
        # names are surfaced even when a newer/unknown provider was persisted.
        providers[credential.provider_name] = True
        models[credential.provider_name] = json.loads(credential.models_json or "[]")
    routes = {}
    for route in db.scalars(select(TaskModelRoute).where(TaskModelRoute.user_id == user_id)):
        model_ref = f"{route.provider_name}:{route.model_id}"
        if route.task == "side_agent":
            routes.setdefault("side_answer", model_ref)
            routes.setdefault("gap_diagnosis", model_ref)
        elif route.task == "knowledge_card":
            routes.setdefault("course_plan", model_ref)
            routes.setdefault("section_content", model_ref)
        else:
            routes[route.task] = model_ref
    return {
        "activeProvider": (
            preference.provider_name if preference else (active.provider_name if active else "mock")
        ),
        "activeModel": (
            preference.model_id if preference else (active.active_model if active else None)
        ),
        "providers": providers,
        "models": models,
        "taskRoutes": routes,
    }


def validate_task_routes(routes: dict[str, str], db: Session) -> None:
    credentials = {
        item.provider_name: item
        for item in db.scalars(
            select(ProviderCredential).where(ProviderCredential.user_id == current_user_id())
        )
    }
    for task, model_ref in routes.items():
        if task not in TASK_BY_ID:
            raise HTTPException(status_code=400, detail=f"Unknown task route: {task}")
        provider_name, separator, model_id = model_ref.partition(":")
        credential = credentials.get(provider_name)
        if not separator or not model_id or not credential:
            raise HTTPException(status_code=400, detail=f"Invalid task model: {model_ref}")
        if model_id not in json.loads(credential.models_json or "[]"):
            raise HTTPException(
                status_code=400,
                detail=f"Model is not selected for provider: {model_ref}",
            )


def save_task_routes(routes: dict[str, str], db: Session) -> None:
    validate_task_routes(routes, db)
    user_id = current_user_id()
    existing = {
        route.task: route
        for route in db.scalars(
            select(TaskModelRoute).where(TaskModelRoute.user_id == user_id)
        )
    }
    for task, model_ref in routes.items():
        provider_name, _, model_id = model_ref.partition(":")
        route = existing.get(task) or TaskModelRoute(user_id=user_id, task=task)
        route.provider_name = provider_name
        route.model_id = model_id
        db.add(route)
    for task, route in existing.items():
        if task not in routes:
            db.delete(route)
