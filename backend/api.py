import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .ai.registry import create_named_text_provider
from .ai.providers.mock import MockTextProvider
from .agents.bridge_agent import BridgeAgent
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .agents.teacher_agent import TeacherAgent
from .db import get_db
from .models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    Message,
    Note,
    ProviderCredential,
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
    RelatedCardProposalResponse,
    TeacherGuidanceResponse,
)
from .security.encryption import EncryptionError, decrypt_secret, encrypt_secret

router = APIRouter()
gateway = AIGateway()
side_agent = SideAgent(gateway)
teacher_agent = TeacherAgent(gateway)
main_agent = MainAgent(gateway)
bridge_agent = BridgeAgent(gateway)
provider_state = {
    "active": "mock",
    "active_model": None,
    "providers": {"deepseek": False, "opencode": False, "openrouter": False},
    "models": {name: [] for name in ("deepseek", "opencode", "openrouter")},
}


def restore_active_provider(db: Session) -> None:
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
    gateway.configure(create_named_text_provider(credential.provider_name, api_key, credential.active_model))
    provider_state["active"] = credential.provider_name
    provider_state["active_model"] = credential.active_model


def provider_settings(db: Session) -> dict:
    credentials = list(db.scalars(select(ProviderCredential)))
    providers = {name: False for name in provider_state["providers"]}
    models = {name: [] for name in provider_state["providers"]}
    active = db.scalar(select(ProviderCredential).where(ProviderCredential.is_active.is_(True)))
    for credential in credentials:
        providers[credential.provider_name] = True
        models[credential.provider_name] = json.loads(credential.models_json)
    return {
        "activeProvider": active.provider_name if active else "mock",
        "activeModel": active.active_model if active else None,
        "providers": providers,
        "models": models,
    }


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
    if payload.default_model not in models:
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
    credential.active_model = payload.default_model
    credential.is_active = True
    for other in db.scalars(select(ProviderCredential).where(ProviderCredential.provider_name != provider_name)):
        other.is_active = False
    db.commit()
    return provider_settings(db)


@router.put("/settings/model", response_model=ProviderSettingsResponse)
def select_model(payload: SelectModelRequest, db: Session = Depends(get_db)):
    active = provider_state["active"]
    if active == "mock" or payload.model not in provider_state["models"].get(active, []):
        raise HTTPException(status_code=400, detail="Model is not available for the active provider")
    gateway.select_model(payload.model)
    credential = db.get(ProviderCredential, active)
    credential.active_model = payload.model
    db.commit()
    provider_state["active_model"] = payload.model
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
    db.commit()
    return provider_settings(db)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
                title=section.get("title", f"第 {index + 1} 节"),
                order_index=index,
                content_markdown=section.get("content_markdown", ""),
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
            .where(KnowledgeCard.space_id == space_id)
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
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


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
    if not card or not section or section.card_id != card_id:
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
    if not db.get(KnowledgeCard, card_id):
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    conversation = Conversation(card_id=card_id, **payload.model_dump())
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/cards/{card_id}/conversations", response_model=list[ConversationResponse])
def list_conversations(card_id: str, db: Session = Depends(get_db)):
    return list(db.scalars(select(Conversation).where(Conversation.card_id == card_id)))


@router.get("/cards/{card_id}/proposals", response_model=list[RelatedCardProposalResponse])
def list_card_proposals(card_id: str, db: Session = Depends(get_db)):
    if not db.get(KnowledgeCard, card_id):
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
    if not db.get(Conversation, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    )


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, payload: CreateMessageRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_message = Message(conversation_id=conversation_id, role="user", content=payload.content)
    db.add(user_message)
    db.commit()

    async def events() -> AsyncIterator[str]:
        yield f"event: message.started\ndata: {json.dumps({'conversationId': conversation_id})}\n\n"
        messages = []
        if conversation.root_question:
            messages.append({"role": "system", "content": conversation.root_question})
        messages.append({"role": "user", "content": payload.content})
        response_parts: list[str] = []
        try:
            async for delta in gateway.stream_text(messages, task="side_agent"):
                response_parts.append(delta)
                yield f"event: message.delta\ndata: {json.dumps({'delta': delta})}\n\n"
        except Exception as exc:
            # Keep text already received before a provider/parser failure. This
            # makes a partially streamed answer available after a refresh.
            if response_parts:
                db.add(Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content="".join(response_parts),
                ))
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
            content="".join(response_parts),
        )
        db.add(assistant)
        db.commit()
        try:
            diagnosis = await side_agent.diagnose(payload.content)
            if diagnosis.diagnosis.has_knowledge_gap:
                yield f"event: diagnosis.updated\ndata: {json.dumps(diagnosis.diagnosis.model_dump(by_alias=True), ensure_ascii=False)}\n\n"
                section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
                source_card = db.get(KnowledgeCard, conversation.card_id) if section else None
                if section and source_card and section.card_id == conversation.card_id:
                    try:
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
                        yield f"event: run.failed\ndata: {json.dumps({'code': 'TEACHER_GUIDANCE_FAILED', 'message': str(exc)}, ensure_ascii=False)}\n\n"
                if diagnosis.proposal:
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
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_DIAGNOSIS_FAILED', 'message': str(exc)})}\n\n"
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
    if not source_card:
        raise HTTPException(status_code=404, detail="Source card not found")
    draft = await main_agent.create_card(f"生成关联知识卡：{proposal.title}\n学习原因：{proposal.reason}")
    card = KnowledgeCard(
        space_id=source_card.space_id,
        parent_card_id=source_card.id,
        source_conversation_id=proposal.conversation_id,
        title=draft.title or proposal.title,
        card_type="related",
        status="active",
    )
    db.add(card)
    db.flush()
    for index, section in enumerate(draft.sections):
        db.add(CardSection(card_id=card.id, title=section.get("title", f"第 {index + 1} 节"), order_index=index, content_markdown=section.get("content_markdown", "")))
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
            "请围绕这个推荐主题帮助我判断是否值得创建一张关联知识卡。"
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
    if not db.get(KnowledgeCard, card_id):
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
