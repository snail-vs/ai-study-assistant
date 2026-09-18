import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .ai.oauth_chatgpt import (
    BROWSER_REDIRECT_URI,
    ChatGptCredential,
    ChatGptOAuthError,
    create_browser_authorization,
    exchange_authorization_code,
    parse_authorization_input,
    poll_device_authorization,
    start_device_authorization,
)
from .ai.providers.chatgpt import CODEX_MODELS, DEFAULT_CODEX_MODEL
from .ai.registry import CHATGPT_PROVIDER, create_named_text_provider
from .ai.providers.mock import MockTextProvider
from .ai.tasks import TASK_BY_ID, TASKS
from .agents.bridge_agent import BridgeAgent
from .agents.assessment_agent import AssessmentAgent
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .agents.teacher_agent import TeacherAgent
from .agents.prompts import QA_TUTOR_SYSTEM
from .agents.registry import default_participants, get_agent, AGENTS
from .assessment import AttemptSubmissionService, LegacyQuizAdapter
from .db import SessionLocal, get_db
from .models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    LearningRuntime,
    LearningRuntimeRecord,
    Message,
    Note,
    now,
    ProviderCredential,
    TaskModelRoute,
    DefaultModelPreference,
    AIRun,
    ActivityAttempt,
    LearningActivity,
    RelatedCardProposal,
    TeacherGuidance,
)
from .schemas import (
    ConversationResponse,
    CreateKnowledgeCardRequest,
    CreateConversationRequest,
    CreateLearningSpaceRequest,
    GenerationStatusResponse,
    RetryLearningSpaceGenerationRequest,
    CreateMessageRequest,
    CreateNoteRequest,
    LearningSpaceList,
    LearningSpaceResponse,
    LearningRuntimeResponse,
    UpdateLearningRuntimeRequest,
    KnowledgeCardResponse,
    MessageResponse,
    NoteResponse,
    UpdateNoteRequest,
    ConfigureProviderRequest,
    DiscoverModelsRequest,
    DiscoverModelsResponse,
    ProviderSettingsResponse,
    ChatGptLoginRequest,
    ChatGptLoginResponse,
    ChatGptLoginCompleteRequest,
    ChatGptLoginStatusRequest,
    ChatGptLoginStatusResponse,
    SelectModelRequest,
    ConfigureTaskRoutesRequest,
    TaskRouteResponse,
    AgentDefinitionResponse,
    AIRunResponse,
    RelatedCardProposalResponse,
    ActivityAttemptResponse,
    LearningActivityResponse,
    SubmitActivityAttemptRequest,
    TeacherGuidanceResponse,
)
from .security.encryption import EncryptionError, decrypt_secret, encrypt_secret
from .security.auth import require_current_user, current_user_id

router = APIRouter(dependencies=[Depends(require_current_user)])
public_router = APIRouter()

course_generation_tasks: dict[str, asyncio.Task] = {}
logger = logging.getLogger("studycenter.api")
gateway = AIGateway()
side_agent = SideAgent(gateway)
teacher_agent = TeacherAgent(gateway)
main_agent = MainAgent(gateway)
bridge_agent = BridgeAgent(gateway)
assessment_agent = AssessmentAgent(gateway)
provider_state = {
    "active": "mock",
    "active_model": None,
    "providers": {"deepseek": False, "google": False, "opencode": False, "openrouter": False, "anthropic": False, "chatgpt": False},
    "models": {name: [] for name in ("deepseek", "google", "opencode", "openrouter", "anthropic", "chatgpt")},
}

RELATION_LABELS = {
    "prerequisite": "前置知识",
    "deep_dive": "深入理解",
    "application": "应用延展",
}


def relation_label(relation_type: str | None) -> str:
    return RELATION_LABELS.get(relation_type or "prerequisite", "学习分支")

# In-flight device-code login sessions, keyed by the session id returned to the
# client. Completed/failed sessions are removed when the client polls them.
chatgpt_login_sessions: dict[str, dict] = {}


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
            refresh_token=decrypt_secret(row.oauth_refresh_ciphertext, row.oauth_refresh_nonce or ""),
            expires_at=row.oauth_expires_at or 0,
            account_id=row.oauth_account_id,
        )
    except EncryptionError:
        return None


def persist_chatgpt_token(user_id: str, credential: ChatGptCredential) -> None:
    """Persist a rotated OAuth token from the provider's refresh callback."""
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
            on_token_refresh=(lambda credential: persist_chatgpt_token(row.user_id, credential)) if row else None,
        )
    if row is None:
        raise ValueError(f"Provider is not configured: {provider_name}")
    api_key = decrypt_secret(row.api_key_ciphertext, row.api_key_nonce)
    return create_named_text_provider(provider_name, api_key, model)


def owned_space(db: Session, space_id: str) -> LearningSpace:
    space = db.scalar(
        select(LearningSpace).where(
            LearningSpace.id == space_id,
            LearningSpace.user_id == current_user_id(),
        )
    )
    if not space:
        raise HTTPException(status_code=404, detail="Learning space not found")
    return space


def owned_card(db: Session, card_id: str) -> KnowledgeCard:
    card = db.scalar(
        select(KnowledgeCard)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(KnowledgeCard.id == card_id, LearningSpace.user_id == current_user_id())
    )
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


def owned_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .join(KnowledgeCard, Conversation.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Conversation.id == conversation_id, LearningSpace.user_id == current_user_id())
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def restore_active_provider(db: Session, user_id: str | None = None) -> AIGateway:
    user_id = user_id or current_user_id()
    preference = db.scalar(select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id))
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
        user_gateway = AIGateway(MockTextProvider())
        provider_state["active"] = "mock"
        provider_state["active_model"] = None
        return user_gateway
    default_model = preference.model_id if preference and preference.provider_name == credential.provider_name else credential.active_model
    try:
        default_provider = build_provider(credential.provider_name, default_model, credential)
    except EncryptionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    task_providers = {}
    routes = list(db.scalars(select(TaskModelRoute).where(TaskModelRoute.user_id == user_id)))
    if not routes:
        # Compatibility with task routes saved before routes became global.
        routes = [
            TaskModelRoute(user_id=user_id, task=task, provider_name=credential.provider_name, model_id=model)
            for task, model in json.loads(credential.task_routes_json or "{}").items()
        ]
    credentials = {
        item.provider_name: item
        for item in db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user_id))
    }
    for route in routes:
        route_credential = credentials.get(route.provider_name)
        if route.task not in TASK_BY_ID or not route_credential:
            continue
        try:
            selected_models = json.loads(route_credential.models_json or "[]")
            if route.model_id in selected_models:
                task_provider = build_provider(route.provider_name, route.model_id, route_credential)
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
    provider_state["active"] = credential.provider_name
    provider_state["active_model"] = default_model
    return user_gateway


def provider_settings(db: Session) -> dict:
    user_id = current_user_id()
    credentials = list(db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user_id)))
    providers = {name: False for name in provider_state["providers"]}
    models = {name: [] for name in provider_state["providers"]}
    preference = db.scalar(select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id))
    active = db.get(ProviderCredential, (user_id, preference.provider_name)) if preference else None
    if active is None:
        active = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == user_id, ProviderCredential.is_active.is_(True)))
    for credential in credentials:
        providers[credential.provider_name] = True
        models[credential.provider_name] = json.loads(credential.models_json)
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
        "activeProvider": preference.provider_name if preference else (active.provider_name if active else "mock"),
        "activeModel": preference.model_id if preference else (active.active_model if active else None),
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
            raise HTTPException(status_code=400, detail=f"Model is not selected for provider: {model_ref}")


def save_task_routes(routes: dict[str, str], db: Session) -> None:
    validate_task_routes(routes, db)
    user_id = current_user_id()
    existing = {route.task: route for route in db.scalars(select(TaskModelRoute).where(TaskModelRoute.user_id == user_id))}
    for task, model_ref in routes.items():
        provider_name, _, model_id = model_ref.partition(":")
        route = existing.get(task) or TaskModelRoute(user_id=user_id, task=task)
        route.provider_name = provider_name
        route.model_id = model_id
        db.add(route)
    for task, route in existing.items():
        if task not in routes:
            db.delete(route)


@router.get("/settings/providers", response_model=ProviderSettingsResponse)
def get_provider_settings(db: Session = Depends(get_db)):
    restore_active_provider(db)
    return provider_settings(db)


@router.post("/settings/providers/{provider_name}/models", response_model=DiscoverModelsResponse)
async def discover_models(provider_name: str, payload: DiscoverModelsRequest, db: Session = Depends(get_db)):
    if provider_name == CHATGPT_PROVIDER:
        credential = db.get(ProviderCredential, (current_user_id(), CHATGPT_PROVIDER))
        if credential is None or credential.auth_type != "oauth":
            raise HTTPException(status_code=400, detail="请先完成 ChatGPT 设备码登录")
        try:
            provider = create_named_text_provider(
                provider_name,
                "",
                oauth=chatgpt_credential(credential),
            )
            models = await provider.list_models()
        except Exception as exc:  # noqa: BLE001 - preserve provider error details for the client
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
def configure_provider(provider_name: str, payload: ConfigureProviderRequest, db: Session = Depends(get_db)):
    user_id = current_user_id()
    models = list(dict.fromkeys(payload.models))
    if payload.default_model is not None and payload.default_model not in models:
        raise HTTPException(status_code=400, detail="Default model must be one of the selected models")
    credential = db.get(ProviderCredential, (user_id, provider_name))
    ciphertext: str | None = None
    nonce: str | None = None
    if provider_name == CHATGPT_PROVIDER:
        if credential is None or credential.auth_type != "oauth":
            raise HTTPException(status_code=400, detail="请先完成 ChatGPT 设备码登录")
        try:
            provider = create_named_text_provider(
                provider_name,
                "",
                payload.default_model,
                oauth=chatgpt_credential(credential),
                on_token_refresh=lambda token: persist_chatgpt_token(user_id, token),
            )
        except (ValueError, EncryptionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        api_key = payload.api_key
        if not api_key:
            if credential is None:
                raise HTTPException(status_code=400, detail="API Key is required for a new provider")
            try:
                api_key = decrypt_secret(credential.api_key_ciphertext, credential.api_key_nonce)
            except EncryptionError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        try:
            if payload.api_key:
                ciphertext, nonce = encrypt_secret(api_key)
            provider = create_named_text_provider(provider_name, api_key, payload.default_model)
        except (ValueError, EncryptionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    gateway.configure(provider)
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
    for other in db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user_id, ProviderCredential.provider_name != provider_name)):
        other.is_active = False
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.put("/settings/model", response_model=ProviderSettingsResponse)
def select_model(payload: SelectModelRequest, db: Session = Depends(get_db)):
    user_id = current_user_id()
    preference = db.scalar(select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id))
    active_credential = db.get(ProviderCredential, (user_id, preference.provider_name)) if preference else None
    if active_credential is None:
        active_credential = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == user_id, ProviderCredential.is_active.is_(True)))
    active = active_credential.provider_name if active_credential else "mock"
    provider_name, separator, model_id = payload.model.partition(":")
    if separator:
        active = provider_name
        active_credential = db.get(ProviderCredential, (user_id, provider_name))
    else:
        model_id = payload.model
    selected_models = json.loads(active_credential.models_json or "[]") if active_credential else []
    if active == "mock" or model_id not in selected_models:
        raise HTTPException(status_code=400, detail="Model is not available for the active provider")
    restore_active_provider(db)
    if preference is None:
        next_id = (db.scalar(select(func.max(DefaultModelPreference.id))) or 0) + 1
        preference = DefaultModelPreference(id=next_id, user_id=user_id)
    preference.provider_name = active
    preference.model_id = model_id
    db.add(preference)
    if active == CHATGPT_PROVIDER:
        gateway.configure(
            create_named_text_provider(
                active,
                "",
                model_id,
                oauth=chatgpt_credential(active_credential),
                on_token_refresh=lambda token: persist_chatgpt_token(user_id, token),
            )
        )
    else:
        gateway.configure(create_named_text_provider(active, decrypt_secret(active_credential.api_key_ciphertext, active_credential.api_key_nonce), model_id))
    db.commit()
    provider_state["active"] = active
    provider_state["active_model"] = model_id
    return provider_settings(db)


@router.get("/settings/model-routes", response_model=list[TaskRouteResponse])
def get_model_routes(db: Session = Depends(get_db)):
    settings = provider_settings(db)
    routes = settings["taskRoutes"]
    return [
        {"id": task.id, "label": task.label, "category": task.category, "model": routes.get(task.id)}
        for task in TASKS
    ]


@router.put("/settings/model-routes", response_model=ProviderSettingsResponse)
def configure_model_routes(payload: ConfigureTaskRoutesRequest, db: Session = Depends(get_db)):
    active = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == current_user_id(), ProviderCredential.is_active.is_(True)))
    if not active:
        raise HTTPException(status_code=400, detail="请先配置一个 AI Provider")
    save_task_routes(payload.routes, db)
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.delete("/settings/providers/{provider_name}", response_model=ProviderSettingsResponse)
def clear_provider(provider_name: str, db: Session = Depends(get_db)):
    if provider_name not in provider_state["providers"]:
        raise HTTPException(status_code=404, detail="Provider not found")
    user_id = current_user_id()
    credential = db.get(ProviderCredential, (user_id, provider_name))
    if credential:
        was_active = credential.is_active
        db.delete(credential)
    else:
        was_active = False
    if was_active:
        gateway.configure(MockTextProvider())
        provider_state["active"] = "mock"
        provider_state["active_model"] = None
    preference = db.scalar(select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id))
    if preference and preference.provider_name == provider_name:
        db.delete(preference)
    db.commit()
    return provider_settings(db)


def save_chatgpt_login(user_id: str, credential: ChatGptCredential) -> None:
    db = SessionLocal()
    try:
        row = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
        if row is None:
            row = ProviderCredential(
                user_id=user_id, provider_name=CHATGPT_PROVIDER, api_key_ciphertext="", api_key_nonce=""
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
    """Best-effort: replace the fallback catalog with the account's real one."""
    try:
        provider = create_named_text_provider(CHATGPT_PROVIDER, "", oauth=credential)
        models = await provider.list_models()
    except Exception:  # noqa: BLE001 - login already succeeded; keep the fallback
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


async def run_chatgpt_device_login(session_id: str, device, user_id: str) -> None:
    session = chatgpt_login_sessions.get(session_id)
    if session is None:
        return
    try:
        credential = await poll_device_authorization(device)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the polling client
        session["status"] = "failed"
        session["error"] = str(exc)
        return
    try:
        save_chatgpt_login(user_id, credential)
    except Exception as exc:  # noqa: BLE001
        session["status"] = "failed"
        session["error"] = f"凭证保存失败: {exc}"
        return
    await refresh_chatgpt_models(user_id, credential)
    session["status"] = "done"
    session["credential"] = credential


@router.post("/settings/providers/chatgpt/oauth/login", response_model=ChatGptLoginResponse)
async def chatgpt_oauth_login(payload: ChatGptLoginRequest):
    session_id = str(uuid4())
    if payload.method == "browser":
        authorization = create_browser_authorization()
        chatgpt_login_sessions[session_id] = {
            "method": "browser",
            "status": "pending",
            "credential": None,
            "error": None,
            "user_id": current_user_id(),
            "verifier": authorization.verifier,
            "state": authorization.state,
        }
        return {"sessionId": session_id, "method": "browser", "authUrl": authorization.url}
    try:
        device = await start_device_authorization()
    except ChatGptOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    user_id = current_user_id()
    session: dict = {"method": "device_code", "status": "pending", "credential": None, "error": None, "user_id": user_id}
    session["task"] = asyncio.create_task(run_chatgpt_device_login(session_id, device, user_id))
    chatgpt_login_sessions[session_id] = session
    return {
        "sessionId": session_id,
        "method": "device_code",
        "userCode": device.user_code,
        "verificationUri": device.verification_uri,
        "intervalSeconds": device.interval_seconds,
    }


@router.post("/settings/providers/chatgpt/oauth/status", response_model=ChatGptLoginStatusResponse)
def chatgpt_oauth_status(payload: ChatGptLoginStatusRequest, db: Session = Depends(get_db)):
    session = chatgpt_login_sessions.get(payload.session_id)
    if session is None:
        return {"state": "unknown"}
    state = session.get("status")
    if state == "done":
        credential: ChatGptCredential = session["credential"]
        chatgpt_login_sessions.pop(payload.session_id, None)
        restore_active_provider(db, session["user_id"])
        return {
            "state": "done",
            "accountId": credential.account_id,
            "expires": credential.expires_at,
        }
    if state == "failed":
        error = session.get("error") or "登录失败"
        chatgpt_login_sessions.pop(payload.session_id, None)
        return {"state": "failed", "error": error}
    return {"state": "pending"}


@router.post("/settings/providers/chatgpt/oauth/complete", response_model=ChatGptLoginStatusResponse)
async def chatgpt_oauth_complete(
    payload: ChatGptLoginCompleteRequest, db: Session = Depends(get_db)
):
    session = chatgpt_login_sessions.get(payload.session_id)
    if session is None:
        return {"state": "unknown"}
    if session.get("method") != "browser":
        raise HTTPException(status_code=400, detail="当前登录会话不是浏览器授权")
    try:
        code, state = parse_authorization_input(payload.input)
        expected_state = session.get("state")
        if state and expected_state and state != expected_state:
            raise ChatGptOAuthError("state 校验失败，请重新发起登录")
        if not code:
            raise ChatGptOAuthError("未在输入中找到授权码")
        credential = await exchange_authorization_code(
            code, session["verifier"], redirect_uri=BROWSER_REDIRECT_URI
        )
    except ChatGptOAuthError as exc:
        session["error"] = str(exc)
        return {"state": "failed", "error": str(exc)}
    try:
        user_id = session.get("user_id") or current_user_id()
        save_chatgpt_login(user_id, credential)
    except Exception as exc:  # noqa: BLE001
        session["error"] = f"凭证保存失败: {exc}"
        return {"state": "failed", "error": session["error"]}
    await refresh_chatgpt_models(user_id, credential)
    chatgpt_login_sessions.pop(payload.session_id, None)
    restore_active_provider(db, user_id)
    return {"state": "done", "accountId": credential.account_id, "expires": credential.expires_at}


@router.post("/settings/providers/chatgpt/oauth/logout", response_model=ProviderSettingsResponse)
def chatgpt_oauth_logout(db: Session = Depends(get_db)):
    user_id = current_user_id()
    credential = db.get(ProviderCredential, (user_id, CHATGPT_PROVIDER))
    if credential is not None:
        was_active = credential.is_active
        db.delete(credential)
        preference = db.scalar(select(DefaultModelPreference).where(DefaultModelPreference.user_id == user_id))
        if preference and preference.provider_name == CHATGPT_PROVIDER:
            db.delete(preference)
        db.commit()
        if was_active:
            gateway.configure(MockTextProvider())
            provider_state["active"] = "mock"
            provider_state["active_model"] = None
    restore_active_provider(db, user_id)
    return provider_settings(db)


@public_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents():
    return AGENTS


async def generate_course(space_id: str, user_id: str, learning_goal: str) -> None:
    db = SessionLocal()
    try:
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        space.generation_status = "running"
        space.generation_phase = "generating"
        space.generation_updated_at = now()
        db.commit()
        gateway = restore_active_provider(db, user_id)
        db.close()
        db = None

        draft = await MainAgent(gateway).create_card(learning_goal)

        db = SessionLocal()
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        space.generation_phase = "saving"
        space.generation_updated_at = now()
        db.commit()
        card = KnowledgeCard(space_id=space.id, title=draft.title, card_type="root", status="active")
        db.add(card)
        db.flush()
        for index, section in enumerate(draft.sections):
            db.add(
                CardSection(
                    card_id=card.id,
                    title=section.title or f"第 {index + 1} 节",
                    order_index=index,
                    content_markdown=section.content_markdown,
                    content_type=section.content_type,
                    teaching_objective=section.teaching_objective,
                    quality_report_json=json.dumps(section.quality_report, ensure_ascii=False),
                )
            )
        space.root_card_id = card.id
        space.generation_status = "completed"
        space.generation_phase = "completed"
        space.generation_error = None
        space.generation_updated_at = now()
        db.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - persist failure for the UI
        logger.exception("course generation failed: space_id=%s", space_id)
        if db is not None:
            db.rollback()
            space = db.get(LearningSpace, space_id)
        else:
            db = SessionLocal()
            space = db.get(LearningSpace, space_id)
        if space:
            space.generation_status = "failed"
            space.generation_phase = "failed"
            space.generation_error = str(exc)
            space.generation_updated_at = now()
            db.commit()
    finally:
        if db is not None:
            db.close()
        course_generation_tasks.pop(space_id, None)


def schedule_course_generation(space_id: str, user_id: str, learning_goal: str) -> None:
    existing = course_generation_tasks.get(space_id)
    if existing and not existing.done():
        return
    course_generation_tasks[space_id] = asyncio.create_task(
        generate_course(space_id, user_id, learning_goal)
    )


async def resume_pending_course_generations() -> None:
    db = SessionLocal()
    try:
        spaces = list(
            db.scalars(
                select(LearningSpace).where(
                    LearningSpace.generation_status.in_(("queued", "running")),
                )
            )
        )
        for space in spaces:
            schedule_course_generation(space.id, space.user_id, space.learning_goal)
    finally:
        db.close()


@router.post("/learning-spaces", response_model=LearningSpaceResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_learning_space(payload: CreateLearningSpaceRequest, db: Session = Depends(get_db)):
    user_id = current_user_id()
    space = LearningSpace(
        user_id=user_id,
        title=payload.title,
        learning_goal=payload.learning_goal,
        generation_status="queued",
        generation_phase="queued",
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, user_id, payload.learning_goal)
    return space


@router.get("/learning-spaces", response_model=LearningSpaceList)
def list_learning_spaces(db: Session = Depends(get_db)):
    return {"items": list(db.scalars(select(LearningSpace).where(LearningSpace.user_id == current_user_id()).order_by(LearningSpace.created_at.desc())))}


@router.get("/learning-spaces/{space_id}", response_model=LearningSpaceResponse)
def get_learning_space(space_id: str, db: Session = Depends(get_db)):
    return owned_space(db, space_id)


@router.get("/learning-spaces/{space_id}/generation", response_model=GenerationStatusResponse)
def get_course_generation_status(space_id: str, db: Session = Depends(get_db)):
    space = owned_space(db, space_id)
    return {
        "spaceId": space.id,
        "status": space.generation_status,
        "phase": space.generation_phase,
        "error": space.generation_error,
        "rootCardId": space.root_card_id,
        "updatedAt": space.generation_updated_at or space.created_at,
    }


@router.put("/learning-spaces/{space_id}/generation", response_model=LearningSpaceResponse)
async def retry_course_generation(
    space_id: str,
    payload: RetryLearningSpaceGenerationRequest,
    db: Session = Depends(get_db),
):
    space = owned_space(db, space_id)
    if space.generation_status != "failed":
        raise HTTPException(status_code=409, detail="Only failed course generations can be retried")
    if space.root_card_id:
        raise HTTPException(status_code=409, detail="A completed course cannot be regenerated")
    space.title = payload.title
    space.learning_goal = payload.learning_goal
    space.generation_status = "queued"
    space.generation_phase = "queued"
    space.generation_error = None
    space.generation_updated_at = now()
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, space.user_id, space.learning_goal)
    return space


@router.get("/learning-spaces/{space_id}/runtime", response_model=LearningRuntimeResponse | None)
def get_learning_runtime(space_id: str, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    return db.scalar(select(LearningRuntime).where(LearningRuntime.space_id == space_id))


@router.put("/learning-spaces/{space_id}/runtime", response_model=LearningRuntimeResponse)
def update_learning_runtime(
    space_id: str,
    payload: UpdateLearningRuntimeRequest,
    db: Session = Depends(get_db),
):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    current_card = db.get(KnowledgeCard, payload.current_card_id)
    if not current_card or current_card.space_id != space_id or current_card.status == "deleted":
        raise HTTPException(status_code=400, detail="Current card does not belong to this learning space")
    if payload.current_section_id:
        current_section = db.get(CardSection, payload.current_section_id)
        if not current_section or current_section.card_id != current_card.id:
            raise HTTPException(status_code=400, detail="Current section does not belong to current card")

    stack = [entry.model_dump(by_alias=True) for entry in payload.navigation_stack]
    for entry in payload.navigation_stack:
        stack_card = db.get(KnowledgeCard, entry.card_id)
        if not stack_card or stack_card.space_id != space_id or stack_card.status == "deleted":
            raise HTTPException(status_code=400, detail="Navigation stack contains an invalid card")
        if entry.section_id:
            stack_section = db.get(CardSection, entry.section_id)
            if not stack_section or stack_section.card_id != stack_card.id:
                raise HTTPException(status_code=400, detail="Navigation stack contains an invalid section")

    runtime = db.scalar(select(LearningRuntime).where(LearningRuntime.space_id == space_id))
    if runtime is None:
        runtime = LearningRuntime(space_id=space_id)
        db.add(runtime)
        db.flush()
    source = payload.navigation_stack[-1] if payload.navigation_stack else None
    runtime.current_card_id = current_card.id
    runtime.current_section_id = payload.current_section_id
    runtime.source_card_id = source.card_id if source else None
    runtime.source_section_id = source.section_id if source else None
    runtime.navigation_stack_json = json.dumps(stack, ensure_ascii=False)
    runtime.updated_at = now()

    latest_seq = db.scalar(
        select(func.max(LearningRuntimeRecord.seq)).where(LearningRuntimeRecord.runtime_id == runtime.id)
    ) or 0
    db.add(LearningRuntimeRecord(
        runtime_id=runtime.id,
        seq=latest_seq + 1,
        event_type=payload.event_type,
        card_id=current_card.id,
        section_id=payload.current_section_id,
        payload_json=json.dumps({"navigationStack": stack}, ensure_ascii=False),
    ))
    db.commit()
    db.refresh(runtime)
    return runtime


@router.get("/learning-spaces/{space_id}/cards", response_model=list[KnowledgeCardResponse])
def list_cards(space_id: str, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    return list(
        db.scalars(
            select(KnowledgeCard)
            .where(KnowledgeCard.space_id == space_id, KnowledgeCard.status != "deleted")
            .order_by(KnowledgeCard.card_type, KnowledgeCard.title)
        )
    )


@router.post("/learning-spaces/{space_id}/cards", response_model=KnowledgeCardResponse, status_code=201)
def create_card(space_id: str, payload: CreateKnowledgeCardRequest, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    card = KnowledgeCard(space_id=space_id, **payload.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.get("/cards/{card_id}", response_model=KnowledgeCardResponse)
def get_card(card_id: str, db: Session = Depends(get_db)):
    card = owned_card(db, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


@router.delete("/cards/{card_id}")
def delete_card(card_id: str, db: Session = Depends(get_db)):
    card = owned_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    if card.status != "deleted":
        card.status = "deleted"
        card.deleted_at = now()
        db.commit()
    return {"status": "deleted", "cardId": card_id}


@router.get("/cards/{card_id}/sections/{section_id}/guidance", response_model=list[TeacherGuidanceResponse])
def list_teacher_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=404, detail="Card section not found")
    return list(
        db.scalars(
            select(TeacherGuidance)
            .where(TeacherGuidance.card_id == card_id, TeacherGuidance.section_id == section_id)
            .order_by(TeacherGuidance.created_at, TeacherGuidance.id)
        )
    )


@router.post("/cards/{card_id}/sections/{section_id}/guidance", response_model=TeacherGuidanceResponse, status_code=201)
async def create_section_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    section = db.get(CardSection, section_id)
    if not card or card.status == "deleted" or not section or section.card_id != card_id:
        raise HTTPException(status_code=404, detail="Card section not found")
    existing = db.scalar(
        select(TeacherGuidance)
        .where(
            TeacherGuidance.card_id == card_id,
            TeacherGuidance.section_id == section_id,
            TeacherGuidance.trigger == "section_enter",
        )
        .order_by(TeacherGuidance.created_at)
    )
    if existing:
        return existing
    draft = await TeacherAgent(restore_active_provider(db)).create_section_intro(
        card.title, section.title, section.content_markdown
    )
    guidance = TeacherGuidance(
        card_id=card_id,
        section_id=section_id,
        trigger="section_enter",
        content=draft.content,
    )
    db.add(guidance)
    db.commit()
    db.refresh(guidance)
    return guidance


@router.post("/cards/{card_id}/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(card_id: str, payload: CreateConversationRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, payload.section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
    participant_ids = payload.participant_ids or default_participants(payload.conversation_type)
    unknown = [agent_id for agent_id in participant_ids if not get_agent(agent_id)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {unknown[0]}")
    values = payload.model_dump(exclude={"participant_ids"})
    values["participant_ids_json"] = json.dumps(participant_ids)
    conversation = Conversation(card_id=card_id, **values)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/cards/{card_id}/conversations", response_model=list[ConversationResponse])
def list_conversations(
    card_id: str,
    section_id: str = Query(alias="sectionId"),
    db: Session = Depends(get_db),
):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.card_id == card_id, Conversation.section_id == section_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
    )


@router.get("/cards/{card_id}/proposals", response_model=list[RelatedCardProposalResponse])
def list_card_proposals(card_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(
        db.scalars(
            select(RelatedCardProposal)
            .where(
                RelatedCardProposal.card_id == card_id,
                RelatedCardProposal.status.in_(("pending", "discussing")),
            )
            .order_by(RelatedCardProposal.created_at.desc())
        )
    )


def _activity_attempt_response(attempt: ActivityAttempt | None) -> dict | None:
    if not attempt:
        return None
    result = json.loads(attempt.result_json or "{}")
    return {
        "id": attempt.id,
        "activityId": attempt.activity_id,
        "status": attempt.status,
        "score": attempt.score,
        "masteryLevel": attempt.mastery_level,
        "diagnosticSummary": attempt.diagnostic_summary,
        "results": result.get("items", []),
        "createdAt": attempt.created_at,
        "completedAt": attempt.completed_at,
    }


def _activity_response(activity: LearningActivity, attempt: ActivityAttempt | None = None) -> dict:
    content = json.loads(activity.content_json or "{}")
    return {
        "id": activity.id,
        "cardId": activity.card_id,
        "sectionId": activity.section_id,
        "activityType": activity.activity_type,
        "title": activity.title,
        "objective": activity.objective,
        "status": activity.status,
        "questions": content.get("questions", []),
        "latestAttempt": _activity_attempt_response(attempt),
        "createdAt": activity.created_at,
    }


def _get_activity(activity_id: str, db: Session) -> LearningActivity:
    activity = db.scalar(
        select(LearningActivity)
        .join(KnowledgeCard, LearningActivity.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(LearningActivity.id == activity_id, LearningSpace.user_id == current_user_id())
    )
    section = db.get(CardSection, activity.section_id) if activity else None
    card = db.get(KnowledgeCard, activity.card_id) if activity else None
    if not activity or not section or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Learning activity not found")
    return activity


@router.get(
    "/cards/{card_id}/sections/{section_id}/activities",
    response_model=list[LearningActivityResponse],
)
def list_section_activities(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    card = db.get(KnowledgeCard, card_id)
    if not section or not card or section.card_id != card_id or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Section not found")
    activities = list(db.scalars(
        select(LearningActivity)
        .where(LearningActivity.card_id == card_id, LearningActivity.section_id == section_id)
        .order_by(LearningActivity.created_at)
    ))
    return [_activity_response(activity, db.scalar(
        select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id)
        .order_by(ActivityAttempt.created_at.desc())
    )) for activity in activities]


@router.post(
    "/cards/{card_id}/sections/{section_id}/activities/quiz",
    response_model=LearningActivityResponse,
)
async def generate_section_quiz(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    card = db.get(KnowledgeCard, card_id)
    if not section or not card or section.card_id != card_id or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Section not found")
    activity = db.scalar(select(LearningActivity).where(
        LearningActivity.section_id == section_id,
        LearningActivity.activity_type == "quiz",
    ))
    if activity and activity.status == "ready":
        attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
        return _activity_response(activity, attempt)
    if activity is None:
        activity = LearningActivity(
            card_id=card_id,
            section_id=section_id,
            activity_type="quiz",
            title="理解检查",
            objective=section.teaching_objective or f"检查是否理解“{section.title}”的核心内容。",
            status="generating",
            content_json="{}",
            answer_key_json="{}",
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
    else:
        activity.status = "generating"
        activity.generation_error = None
        db.commit()
    try:
        draft = await AssessmentAgent(restore_active_provider(db)).generate_quiz(
            card.title,
            section.title,
            activity.objective or "检查本节核心内容",
            section.content_markdown,
        )
        activity.title = draft.title
        activity.objective = draft.objective
        activity.content_json = json.dumps(
            {"version": 1, "questions": [item.model_dump(mode="json") for item in draft.questions]},
            ensure_ascii=False,
        )
        activity.answer_key_json = json.dumps(
            {item.question_id: item.model_dump(mode="json", by_alias=True) for item in draft.answer_key},
            ensure_ascii=False,
        )
        activity.status = "ready"
        db.commit()
        db.refresh(activity)
        return _activity_response(activity)
    except Exception as exc:
        activity.status = "failed"
        activity.generation_error = str(exc)
        db.commit()
        raise


@router.get("/activities/{activity_id}", response_model=LearningActivityResponse)
def get_learning_activity(activity_id: str, db: Session = Depends(get_db)):
    activity = _get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
    return _activity_response(activity, attempt)


@router.get("/activities/{activity_id}/attempts/latest", response_model=ActivityAttemptResponse | None)
def get_latest_activity_attempt(activity_id: str, db: Session = Depends(get_db)):
    activity = _get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
    return _activity_attempt_response(attempt)


@router.post("/activities/{activity_id}/attempts", response_model=ActivityAttemptResponse)
async def submit_activity_attempt(
    activity_id: str,
    payload: SubmitActivityAttemptRequest,
    db: Session = Depends(get_db),
):
    activity = _get_activity(activity_id, db)
    if activity.status != "ready":
        raise HTTPException(status_code=409, detail="Learning activity is not ready")
    section = db.get(CardSection, activity.section_id)
    card = db.get(KnowledgeCard, activity.card_id)
    assessment = LegacyQuizAdapter.from_json(
        activity_id=activity.id,
        objective=activity.objective,
        section_content=section.content_markdown if section else "",
        content=json.loads(activity.content_json or "{}"),
        answer_key=json.loads(activity.answer_key_json or "{}"),
    )
    def short_answer_evaluator_factory():
        # Preserve the old per-short-answer provider restoration behavior while
        # keeping objective-only submissions completely deterministic.
        return AssessmentAgent(restore_active_provider(db)).evaluate_short_answer

    service = AttemptSubmissionService(short_answer_evaluator_factory=short_answer_evaluator_factory)
    submission = await service.submit(db, activity, assessment, payload.answers)
    attempt = submission.attempt
    evaluation = submission.evaluation
    score = evaluation.score
    diagnostic = evaluation.diagnostic_summary
    misconceptions = list(evaluation.misconceptions)

    if card and section:
        try:
            guidance = await TeacherAgent(restore_active_provider(db)).create_activity_followup(
                card.title, section.title, activity.objective or "", score, diagnostic,
            )
            db.add(TeacherGuidance(
                card_id=card.id,
                section_id=section.id,
                source_conversation_id=None,
                trigger="activity_result",
                content=guidance.content,
            ))
            db.commit()
        except Exception:
            logger.exception("activity mentor follow-up failed: activity_id=%s", activity.id)
    if score < 60 and card and section:
        try:
            diagnosis = await SideAgent(restore_active_provider(db)).diagnose(
                "；".join(misconceptions) or diagnostic,
                context=f"知识卡：{card.title}\n章节：{section.title}\n课程内容：{section.content_markdown}",
            )
            if diagnosis.proposal:
                db.add(RelatedCardProposal(
                    conversation_id=None,
                    activity_id=activity.id,
                    card_id=card.id,
                    section_id=section.id,
                    title=diagnosis.proposal.title,
                    reason=diagnosis.proposal.reason,
                    relation_type=diagnosis.proposal.relation_type,
                ))
                db.commit()
        except Exception:
            logger.exception("activity gap diagnosis failed: activity_id=%s", activity.id)
    return _activity_attempt_response(attempt)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    )


@router.get("/conversations/{conversation_id}/runs/active", response_model=AIRunResponse | None)
def get_active_run(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if run and run.updated_at and (now() - run.updated_at).total_seconds() > 180:
        run.status = "expired"
        run.phase = "expired"
        run.error_message = "AI 请求可能已中断，请重新发送。"
        db.commit()
    return run


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, payload: CreateMessageRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation.section_id:
        raise HTTPException(status_code=409, detail="Legacy course-level conversations cannot receive section messages")
    if payload.section_id != conversation.section_id:
        raise HTTPException(status_code=409, detail="Conversation belongs to a different section")
    active_run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if active_run:
        raise HTTPException(status_code=409, detail="该问题讨论正在处理上一条消息，请稍候")

    primary_agent_id = conversation.participant_ids[0] if conversation.participant_ids else (
        "teacher" if conversation.conversation_type == "main" else "side_tutor"
    )
    primary_agent = get_agent(primary_agent_id)
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        sender_id="user",
        sender_name="你",
        sender_role="user",
        visibility="user",
        content=payload.content,
    )
    db.add(user_message)
    run = AIRun(conversation_id=conversation_id, run_type="side_message", status="running", phase="waiting")
    db.add(run)
    db.commit()

    async def events() -> AsyncIterator[str]:
        message_id = str(uuid4())
        yield f"event: run.started\ndata: {json.dumps({'conversationId': conversation_id, 'runId': run.id, 'phase': 'waiting', 'label': '正在等待 AI 响应'}, ensure_ascii=False)}\n\n"
        yield f"event: message.started\ndata: {json.dumps({'conversationId': conversation_id, 'messageId': message_id, 'senderId': primary_agent_id, 'senderName': primary_agent.name if primary_agent else primary_agent_id, 'senderRole': primary_agent.role if primary_agent else 'assistant'}, ensure_ascii=False)}\n\n"
        answer_section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
        messages = [{"role": "system", "content": QA_TUTOR_SYSTEM}]
        answer_context = ""
        if answer_section:
            answer_context = (
                f"当前知识卡：{card.title}\n当前章节：{answer_section.title}\n"
                f"课程内容：{answer_section.content_markdown[:6000]}"
            )
            messages.append({
                "role": "system",
                "content": answer_context,
            })
        try:
            yield f"event: run.phase\ndata: {json.dumps({'phase': 'planning', 'label': '正在理解问题并组织回答'}, ensure_ascii=False)}\n\n"
            run.phase = "planning"
            db.commit()
            answer_plan = await SideAgent(restore_active_provider(db)).plan_answer(
                payload.content,
                context=answer_context,
            )
            length_budget = {"short": "80～200", "medium": "200～400", "long": "400～700"}[answer_plan.target_length]
            messages.append({
                "role": "system",
                "content": (
                    "请严格依据下面的回答计划作答，不要扩展计划之外的背景知识。\n"
                    f"回答类型：{answer_plan.intent}\n直接答案：{answer_plan.direct_answer}\n"
                    f"必要要点：{json.dumps(answer_plan.key_points, ensure_ascii=False)}\n"
                    f"是否需要例子：{'是' if answer_plan.needs_example else '否'}\n"
                    f"目标长度：{length_budget} 个中文字符。"
                ),
            })
        except Exception:
            logger.exception("side answer planning failed; falling back to direct answer")
        yield f"event: run.phase\ndata: {json.dumps({'phase': 'answering', 'label': '答疑助教正在回答'}, ensure_ascii=False)}\n\n"
        run.phase = "answering"
        db.commit()
        if conversation.root_question:
            messages.append({"role": "system", "content": f"本讨论的起始问题：{conversation.root_question}"})
        history = list(db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.visibility == "user")
            .order_by(Message.created_at, Message.id)
        ))[-8:]
        messages.extend({"role": item.role, "content": item.content} for item in history)
        response_parts: list[str] = []
        try:
            async for delta in restore_active_provider(db).stream_text(messages, task="side_answer"):
                response_parts.append(delta)
                yield f"event: message.delta\ndata: {json.dumps({'messageId': message_id, 'senderId': primary_agent_id, 'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            # Keep text already received before a provider/parser failure. This
            # makes a partially streamed answer available after a refresh.
            if response_parts:
                db.add(Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    sender_id=primary_agent_id,
                    sender_name=primary_agent.name if primary_agent else primary_agent_id,
                    sender_role=primary_agent.role if primary_agent else "assistant",
                    visibility="user",
                    content="".join(response_parts),
                ))
                db.commit()
            run.status = "failed"
            run.phase = "answering"
            run.error_message = str(exc)
            db.commit()
            message = str(exc)
            if "MissingSessionID" in message or "only be used in OpenCode" in message:
                message = "OpenCode 免费模型只能在 OpenCode 会话中使用，请改用 OpenCode 付费模型、DeepSeek 或 OpenRouter 模型。"
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_PROVIDER_ERROR', 'message': message}, ensure_ascii=False)}\n\n"
            yield "event: message.completed\ndata: {}\n\n"
            return
        assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            sender_id=primary_agent_id,
            sender_name=primary_agent.name if primary_agent else primary_agent_id,
            sender_role=primary_agent.role if primary_agent else "assistant",
            visibility="user",
            content="".join(response_parts),
        )
        db.add(assistant)
        db.commit()
        try:
            # 每次答疑后都由课程导师做一次归位，帮助学生回到当前章节。
            # 这一步不依赖知识断层诊断；诊断只负责后续的推荐知识卡。
            section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
            source_card = db.get(KnowledgeCard, conversation.card_id) if section else None
            if not section or not source_card or section.card_id != conversation.card_id:
                logger.warning(
                    "skip teacher guidance: conversation_id=%s card_id=%s conversation_section_id=%s payload_section_id=%s",
                    conversation.id,
                    conversation.card_id,
                    conversation.section_id,
                    payload.section_id,
                )
            if section and source_card and section.card_id == conversation.card_id:
                try:
                    yield f"event: run.phase\ndata: {json.dumps({'phase': 'guiding', 'label': '课程导师正在引导归位'}, ensure_ascii=False)}\n\n"
                    run.phase = "guiding"
                    db.commit()
                    guidance_draft = await TeacherAgent(restore_active_provider(db)).create_side_followup(
                        source_card.title,
                        section.title,
                        section.content_markdown,
                        payload.content,
                        "".join(response_parts),
                    )
                    guidance = TeacherGuidance(
                        card_id=conversation.card_id,
                        section_id=section.id,
                        source_conversation_id=conversation.id,
                        source_question_message_id=user_message.id,
                        source_answer_message_id=assistant.id,
                        source_question=payload.content,
                        trigger="side_question",
                        content=guidance_draft.content,
                    )
                    db.add(guidance)
                    db.commit()
                    db.refresh(guidance)
                    yield f"event: guidance.updated\ndata: {json.dumps(TeacherGuidanceResponse.model_validate(guidance).model_dump(by_alias=True), default=str, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.exception(
                        "teacher guidance failed: conversation_id=%s card_id=%s section_id=%s",
                        conversation.id,
                        conversation.card_id,
                        section.id,
                    )
                    yield f"event: guidance.failed\ndata: {json.dumps({'code': 'TEACHER_GUIDANCE_FAILED', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            yield f"event: run.phase\ndata: {json.dumps({'phase': 'diagnosing', 'label': '正在分析你的知识断层'}, ensure_ascii=False)}\n\n"
            run.phase = "diagnosing"
            db.commit()
            diagnosis = await SideAgent(restore_active_provider(db)).diagnose(
                payload.content,
                context=(
                    f"知识卡：{source_card.title}\n章节：{section.title}\n课程内容：{section.content_markdown}"
                    if section and source_card else ""
                ),
            )
            logger.info(
                "side-agent diagnosis: conversation_id=%s has_knowledge_gap=%s missing_topics=%s proposal=%s",
                conversation.id,
                diagnosis.diagnosis.has_knowledge_gap,
                diagnosis.diagnosis.missing_topics,
                diagnosis.proposal.title if diagnosis.proposal else None,
            )
            if diagnosis.diagnosis.has_knowledge_gap or diagnosis.proposal:
                yield f"event: diagnosis.updated\ndata: {json.dumps(diagnosis.diagnosis.model_dump(by_alias=True), ensure_ascii=False)}\n\n"
                if diagnosis.proposal:
                    yield f"event: run.phase\ndata: {json.dumps({'phase': 'recommending', 'label': '正在整理相关学习建议'}, ensure_ascii=False)}\n\n"
                    proposal = diagnosis.proposal.model_dump()
                    stored = RelatedCardProposal(
                        conversation_id=conversation_id,
                        card_id=conversation.card_id,
                        section_id=conversation.section_id,
                        title=proposal["title"],
                        reason=proposal["reason"],
                        relation_type=proposal["relation_type"],
                    )
                    db.add(stored)
                    db.commit()
                    proposal["proposalId"] = stored.id
                    proposal["relationType"] = proposal.pop("relation_type")
                    yield f"event: related_card.proposed\ndata: {json.dumps(proposal, ensure_ascii=False)}\n\n"
        except Exception as exc:
            run.status = "failed"
            run.phase = "diagnosing"
            run.error_message = str(exc)
            db.commit()
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_DIAGNOSIS_FAILED', 'message': str(exc)})}\n\n"
        if run.status != "failed":
            run.status = "completed"
            run.phase = "completed"
            db.commit()
        yield f"event: run.completed\ndata: {json.dumps({'conversationId': conversation_id}, ensure_ascii=False)}\n\n"
        yield "event: message.completed\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/proposals/{proposal_id}/accept", response_model=KnowledgeCardResponse, status_code=201)
async def accept_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    if proposal.generated_card_id:
        card = db.get(KnowledgeCard, proposal.generated_card_id)
        if card:
            return card
    source_card = db.get(KnowledgeCard, proposal.card_id)
    if not source_card or source_card.status == "deleted":
        raise HTTPException(status_code=404, detail="Source card not found")
    draft = await MainAgent(restore_active_provider(db)).create_card(
        f"生成学习分支知识卡：{proposal.title}\n学习原因：{proposal.reason}"
    )
    card = KnowledgeCard(
        space_id=source_card.space_id,
        parent_card_id=source_card.id,
        parent_section_id=proposal.section_id,
        source_conversation_id=proposal.conversation_id,
        title=draft.title or proposal.title,
        card_type="related",
        relation_type=proposal.relation_type,
        status="active",
    )
    db.add(card)
    db.flush()
    for index, section in enumerate(draft.sections):
        db.add(CardSection(
            card_id=card.id,
            title=section.title or f"第 {index + 1} 节",
            order_index=index,
            content_markdown=section.content_markdown,
            content_type=section.content_type,
            teaching_objective=section.teaching_objective,
            quality_report_json=json.dumps(section.quality_report, ensure_ascii=False),
        ))
    bridge = await BridgeAgent(restore_active_provider(db)).create(source_card.title, card.title)
    db.add(BridgeNote(card_id=source_card.id, related_card_id=card.id, content=bridge.content))
    proposal.status = "accepted"
    proposal.generated_card_id = card.id
    db.commit()
    db.refresh(card)
    return card


@router.post("/proposals/{proposal_id}/discussion", response_model=ConversationResponse, status_code=201)
def start_proposal_discussion(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    if proposal.generated_card_id:
        raise HTTPException(status_code=400, detail="Proposal has already been accepted")
    section = db.get(CardSection, proposal.section_id) if proposal.section_id else None
    if not section or section.card_id != proposal.card_id:
        raise HTTPException(status_code=409, detail="Proposal is not associated with a valid course section")
    conversation = Conversation(
        card_id=proposal.card_id,
        section_id=proposal.section_id,
        conversation_type="side",
        title=f"讨论：{proposal.title}",
        root_question=(
            f"推荐学习主题：{proposal.title}\n"
            f"推荐原因：{proposal.reason}\n"
            f"请围绕这个{relation_label(proposal.relation_type)}建议帮助我判断是否值得创建一条学习分支。"
        ),
    )
    db.add(conversation)
    proposal.status = "discussing"
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    proposal.status = "rejected"
    db.commit()
    return {"status": "rejected", "proposalId": proposal_id}


@router.post("/cards/{card_id}/notes", response_model=NoteResponse, status_code=201)
def create_note(card_id: str, payload: CreateNoteRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    values = payload.model_dump()
    values["title"] = values.get("title") or values["content"].splitlines()[0][:200] or "未命名笔记"
    note = Note(card_id=card_id, **values)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/cards/{card_id}/notes", response_model=list[NoteResponse])
def list_notes(card_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(db.scalars(select(Note).where(Note.card_id == card_id).order_by(Note.updated_at.desc())))


@router.get("/notes", response_model=list[NoteResponse])
def list_all_notes(db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(LearningSpace.user_id == current_user_id())
        .order_by(Note.updated_at.desc())
    ))


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: str, payload: UpdateNoteRequest, db: Session = Depends(get_db)):
    note = db.scalar(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Note.id == note_id, LearningSpace.user_id == current_user_id())
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    values = payload.model_dump(exclude_unset=True)
    if "content" in values and not values["content"].strip():
        raise HTTPException(status_code=400, detail="Note content cannot be empty")
    for key, value in values.items():
        if value is not None:
            setattr(note, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, db: Session = Depends(get_db)):
    note = db.scalar(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Note.id == note_id, LearningSpace.user_id == current_user_id())
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"status": "deleted", "noteId": note_id}
