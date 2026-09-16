import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .ai.registry import create_named_text_provider
from .ai.providers.mock import MockTextProvider
from .ai.tasks import TASK_BY_ID, TASKS
from .agents.bridge_agent import BridgeAgent
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .agents.teacher_agent import TeacherAgent
from .agents.prompts import QA_TUTOR_SYSTEM
from .agents.registry import default_participants, get_agent, AGENTS
from .db import get_db
from .models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    Message,
    Note,
    now,
    ProviderCredential,
    TaskModelRoute,
    DefaultModelPreference,
    AIRun,
    RelatedCardProposal,
    TeacherGuidance,
)
from .schemas import (
    ConversationResponse,
    CreateKnowledgeCardRequest,
    CreateConversationRequest,
    CreateLearningSpaceRequest,
    CreateMessageRequest,
    CreateNoteRequest,
    LearningSpaceList,
    LearningSpaceResponse,
    KnowledgeCardResponse,
    MessageResponse,
    NoteResponse,
    UpdateNoteRequest,
    ConfigureProviderRequest,
    DiscoverModelsRequest,
    DiscoverModelsResponse,
    ProviderSettingsResponse,
    SelectModelRequest,
    ConfigureTaskRoutesRequest,
    TaskRouteResponse,
    AgentDefinitionResponse,
    AIRunResponse,
    RelatedCardProposalResponse,
    TeacherGuidanceResponse,
)
from .security.encryption import EncryptionError, decrypt_secret, encrypt_secret

router = APIRouter()
logger = logging.getLogger("studycenter.api")
gateway = AIGateway()
side_agent = SideAgent(gateway)
teacher_agent = TeacherAgent(gateway)
main_agent = MainAgent(gateway)
bridge_agent = BridgeAgent(gateway)
provider_state = {
    "active": "mock",
    "active_model": None,
    "providers": {"deepseek": False, "google": False, "opencode": False, "openrouter": False},
    "models": {name: [] for name in ("deepseek", "google", "opencode", "openrouter")},
}


def restore_active_provider(db: Session) -> None:
    preference = db.get(DefaultModelPreference, 1)
    credential = db.get(ProviderCredential, preference.provider_name) if preference else None
    if credential is None:
        credential = db.scalar(select(ProviderCredential).where(ProviderCredential.is_active.is_(True)))
    if not credential:
        gateway.configure(MockTextProvider())
        provider_state["active"] = "mock"
        provider_state["active_model"] = None
        return
    try:
        api_key = decrypt_secret(credential.api_key_ciphertext, credential.api_key_nonce)
    except EncryptionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    default_model = preference.model_id if preference and preference.provider_name == credential.provider_name else credential.active_model
    default_provider = create_named_text_provider(credential.provider_name, api_key, default_model)
    task_providers = {}
    routes = list(db.scalars(select(TaskModelRoute)))
    if not routes:
        # Compatibility with task routes saved before routes became global.
        routes = [
            TaskModelRoute(task=task, provider_name=credential.provider_name, model_id=model)
            for task, model in json.loads(credential.task_routes_json or "{}").items()
        ]
    credentials = {item.provider_name: item for item in db.scalars(select(ProviderCredential))}
    for route in routes:
        route_credential = credentials.get(route.provider_name)
        if route.task not in TASK_BY_ID or not route_credential:
            continue
        try:
            route_key = decrypt_secret(route_credential.api_key_ciphertext, route_credential.api_key_nonce)
            selected_models = json.loads(route_credential.models_json or "[]")
            if route.model_id in selected_models:
                task_provider = create_named_text_provider(route.provider_name, route_key, route.model_id)
                if route.task == "side_agent":
                    task_providers.setdefault("side_answer", task_provider)
                    task_providers.setdefault("gap_diagnosis", task_provider)
                else:
                    task_providers[route.task] = task_provider
        except (EncryptionError, ValueError):
            continue
    gateway.configure(default_provider, task_providers)
    provider_state["active"] = credential.provider_name
    provider_state["active_model"] = default_model


def provider_settings(db: Session) -> dict:
    credentials = list(db.scalars(select(ProviderCredential)))
    providers = {name: False for name in provider_state["providers"]}
    models = {name: [] for name in provider_state["providers"]}
    preference = db.get(DefaultModelPreference, 1)
    active = db.get(ProviderCredential, preference.provider_name) if preference else None
    if active is None:
        active = db.scalar(select(ProviderCredential).where(ProviderCredential.is_active.is_(True)))
    for credential in credentials:
        providers[credential.provider_name] = True
        models[credential.provider_name] = json.loads(credential.models_json)
    routes = {}
    for route in db.scalars(select(TaskModelRoute)):
        model_ref = f"{route.provider_name}:{route.model_id}"
        if route.task == "side_agent":
            routes.setdefault("side_answer", model_ref)
            routes.setdefault("gap_diagnosis", model_ref)
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
    credentials = {item.provider_name: item for item in db.scalars(select(ProviderCredential))}
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
    existing = {route.task: route for route in db.scalars(select(TaskModelRoute))}
    for task, model_ref in routes.items():
        provider_name, _, model_id = model_ref.partition(":")
        route = existing.get(task) or TaskModelRoute(task=task)
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
    api_key = payload.api_key
    if not api_key:
        credential = db.get(ProviderCredential, provider_name)
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
    models = list(dict.fromkeys(payload.models))
    if payload.default_model is not None and payload.default_model not in models:
        raise HTTPException(status_code=400, detail="Default model must be one of the selected models")
    credential = db.get(ProviderCredential, provider_name)
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
        gateway.configure(create_named_text_provider(provider_name, api_key, payload.default_model))
    except (ValueError, EncryptionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if credential is None:
        credential = ProviderCredential(provider_name=provider_name)
        db.add(credential)
    if payload.api_key:
        credential.api_key_ciphertext = ciphertext
        credential.api_key_nonce = nonce
    credential.models_json = json.dumps(models)
    if credential.active_model is None and models:
        credential.active_model = models[0]
    if payload.task_routes is not None:
        db.flush()
        save_task_routes(payload.task_routes, db)
    credential.is_active = True
    for other in db.scalars(select(ProviderCredential).where(ProviderCredential.provider_name != provider_name)):
        other.is_active = False
    db.commit()
    restore_active_provider(db)
    return provider_settings(db)


@router.put("/settings/model", response_model=ProviderSettingsResponse)
def select_model(payload: SelectModelRequest, db: Session = Depends(get_db)):
    preference = db.get(DefaultModelPreference, 1)
    active_credential = db.get(ProviderCredential, preference.provider_name) if preference else None
    if active_credential is None:
        active_credential = db.scalar(select(ProviderCredential).where(ProviderCredential.is_active.is_(True)))
    active = active_credential.provider_name if active_credential else "mock"
    provider_name, separator, model_id = payload.model.partition(":")
    if separator:
        active = provider_name
        active_credential = db.get(ProviderCredential, provider_name)
    else:
        model_id = payload.model
    selected_models = json.loads(active_credential.models_json or "[]") if active_credential else []
    if active == "mock" or model_id not in selected_models:
        raise HTTPException(status_code=400, detail="Model is not available for the active provider")
    restore_active_provider(db)
    preference = preference or DefaultModelPreference(id=1)
    preference.provider_name = active
    preference.model_id = model_id
    db.add(preference)
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
    active = db.scalar(select(ProviderCredential).where(ProviderCredential.is_active.is_(True)))
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
    credential = db.get(ProviderCredential, provider_name)
    if credential:
        was_active = credential.is_active
        db.delete(credential)
    else:
        was_active = False
    if was_active:
        gateway.configure(MockTextProvider())
        provider_state["active"] = "mock"
        provider_state["active_model"] = None
    preference = db.get(DefaultModelPreference, 1)
    if preference and preference.provider_name == provider_name:
        db.delete(preference)
    db.commit()
    return provider_settings(db)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents():
    return AGENTS


@router.post("/learning-spaces", response_model=LearningSpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_learning_space(payload: CreateLearningSpaceRequest, db: Session = Depends(get_db)):
    restore_active_provider(db)
    space = LearningSpace(title=payload.title, learning_goal=payload.learning_goal)
    db.add(space)
    db.flush()
    draft = await main_agent.create_card(payload.learning_goal)
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
            )
        )
    space.root_card_id = card.id
    db.commit()
    db.refresh(space)
    return space


@router.get("/learning-spaces", response_model=LearningSpaceList)
def list_learning_spaces(db: Session = Depends(get_db)):
    return {"items": list(db.scalars(select(LearningSpace).order_by(LearningSpace.created_at.desc())))}


@router.get("/learning-spaces/{space_id}", response_model=LearningSpaceResponse)
def get_learning_space(space_id: str, db: Session = Depends(get_db)):
    space = db.get(LearningSpace, space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Learning space not found")
    return space


@router.get("/learning-spaces/{space_id}/cards", response_model=list[KnowledgeCardResponse])
def list_cards(space_id: str, db: Session = Depends(get_db)):
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
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    card = KnowledgeCard(space_id=space_id, **payload.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.get("/cards/{card_id}", response_model=KnowledgeCardResponse)
def get_card(card_id: str, db: Session = Depends(get_db)):
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


@router.delete("/cards/{card_id}")
def delete_card(card_id: str, db: Session = Depends(get_db)):
    card = db.get(KnowledgeCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    if card.status != "deleted":
        card.status = "deleted"
        card.deleted_at = now()
        db.commit()
    return {"status": "deleted", "cardId": card_id}


@router.get("/cards/{card_id}/sections/{section_id}/guidance", response_model=list[TeacherGuidanceResponse])
def list_teacher_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
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
    draft = await teacher_agent.create_section_intro(card.title, section.title, section.content_markdown)
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
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
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
def list_conversations(card_id: str, db: Session = Depends(get_db)):
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(db.scalars(select(Conversation).where(Conversation.card_id == card_id)))


@router.get("/cards/{card_id}/proposals", response_model=list[RelatedCardProposalResponse])
def list_card_proposals(card_id: str, db: Session = Depends(get_db)):
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


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
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
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
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
        yield f"event: run.phase\ndata: {json.dumps({'phase': 'answering', 'label': '答疑助教正在回答'}, ensure_ascii=False)}\n\n"
        run.phase = "answering"
        db.commit()
        answer_section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
        if not answer_section and payload.section_id:
            candidate = db.get(CardSection, payload.section_id)
            if candidate and candidate.card_id == conversation.card_id:
                answer_section = candidate
        messages = [{"role": "system", "content": QA_TUTOR_SYSTEM}]
        if answer_section:
            messages.append({
                "role": "system",
                "content": (
                    f"当前知识卡：{card.title}\n当前章节：{answer_section.title}\n"
                    f"课程内容：{answer_section.content_markdown[:6000]}"
                ),
            })
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
            async for delta in gateway.stream_text(messages, task="side_answer"):
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
            # 兼容历史上没有章节绑定的旁支会话：优先使用会话绑定章节，
            # 否则使用客户端发送的当前章节，并把绑定补回数据库。
            section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
            if not section and payload.section_id:
                candidate = db.get(CardSection, payload.section_id)
                if candidate and candidate.card_id == conversation.card_id:
                    section = candidate
                    conversation.section_id = candidate.id
                    db.commit()
                    logger.info(
                        "backfilled conversation section: conversation_id=%s section_id=%s",
                        conversation.id,
                        candidate.id,
                    )
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
                    guidance_draft = await teacher_agent.create_side_followup(
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
            diagnosis = await side_agent.diagnose(
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
                    )
                    db.add(stored)
                    db.commit()
                    proposal["proposalId"] = stored.id
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
    if proposal.generated_card_id:
        card = db.get(KnowledgeCard, proposal.generated_card_id)
        if card:
            return card
    source_card = db.get(KnowledgeCard, proposal.card_id)
    if not source_card or source_card.status == "deleted":
        raise HTTPException(status_code=404, detail="Source card not found")
    draft = await main_agent.create_card(f"生成学习分支知识卡：{proposal.title}\n学习原因：{proposal.reason}")
    card = KnowledgeCard(
        space_id=source_card.space_id,
        parent_card_id=source_card.id,
        parent_section_id=proposal.section_id,
        source_conversation_id=proposal.conversation_id,
        title=draft.title or proposal.title,
        card_type="related",
        status="active",
    )
    db.add(card)
    db.flush()
    for index, section in enumerate(draft.sections):
        db.add(CardSection(card_id=card.id, title=section.title or f"第 {index + 1} 节", order_index=index, content_markdown=section.content_markdown))
    bridge = await bridge_agent.create(source_card.title, card.title)
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
    if proposal.generated_card_id:
        raise HTTPException(status_code=400, detail="Proposal has already been accepted")
    conversation = Conversation(
        card_id=proposal.card_id,
        section_id=proposal.section_id,
        conversation_type="side",
        title=f"讨论：{proposal.title}",
        root_question=(
            f"推荐学习主题：{proposal.title}\n"
            f"推荐原因：{proposal.reason}\n"
            "请围绕这个前置知识建议帮助我判断是否值得创建一条学习分支。"
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
    proposal.status = "rejected"
    db.commit()
    return {"status": "rejected", "proposalId": proposal_id}


@router.post("/cards/{card_id}/notes", response_model=NoteResponse, status_code=201)
def create_note(card_id: str, payload: CreateNoteRequest, db: Session = Depends(get_db)):
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
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(db.scalars(select(Note).where(Note.card_id == card_id).order_by(Note.updated_at.desc())))


@router.get("/notes", response_model=list[NoteResponse])
def list_all_notes(db: Session = Depends(get_db)):
    return list(db.scalars(select(Note).order_by(Note.updated_at.desc())))


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: str, payload: UpdateNoteRequest, db: Session = Depends(get_db)):
    note = db.get(Note, note_id)
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
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"status": "deleted", "noteId": note_id}
