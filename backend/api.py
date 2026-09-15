import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .ai.registry import create_named_text_provider, models_for_provider
from .ai.providers.mock import MockTextProvider
from .agents.bridge_agent import BridgeAgent
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .db import get_db
from .models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    Message,
    Note,
    RelatedCardProposal,
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
    ConfigureProviderRequest,
    ProviderSettingsResponse,
    SelectModelRequest,
)

router = APIRouter()
gateway = AIGateway()
side_agent = SideAgent(gateway)
main_agent = MainAgent(gateway)
bridge_agent = BridgeAgent(gateway)
provider_state = {
    "active": "mock",
    "active_model": None,
    "providers": {"deepseek": False, "opencode": False, "openrouter": False},
    "models": {name: models_for_provider(name) for name in ("deepseek", "opencode", "openrouter")},
}


@router.get("/settings/providers", response_model=ProviderSettingsResponse)
def get_provider_settings():
    return {"activeProvider": provider_state["active"], "activeModel": provider_state["active_model"], "providers": provider_state["providers"], "models": provider_state["models"]}


@router.put("/settings/providers/{provider_name}", response_model=ProviderSettingsResponse)
def configure_provider(provider_name: str, payload: ConfigureProviderRequest):
    try:
        gateway.configure(create_named_text_provider(provider_name, payload.api_key))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider_state["active"] = provider_name
    provider_state["active_model"] = models_for_provider(provider_name)[0]
    provider_state["providers"][provider_name] = True
    return get_provider_settings()


@router.put("/settings/model", response_model=ProviderSettingsResponse)
def select_model(payload: SelectModelRequest):
    active = provider_state["active"]
    if active == "mock" or payload.model not in provider_state["models"].get(active, []):
        raise HTTPException(status_code=400, detail="Model is not available for the active provider")
    gateway.select_model(payload.model)
    provider_state["active_model"] = payload.model
    return get_provider_settings()


@router.delete("/settings/providers/{provider_name}", response_model=ProviderSettingsResponse)
def clear_provider(provider_name: str):
    if provider_name not in provider_state["providers"]:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider_state["providers"][provider_name] = False
    if provider_state["active"] == provider_name:
        gateway.configure(MockTextProvider())
        provider_state["active"] = "mock"
        provider_state["active_model"] = None
    return get_provider_settings()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/learning-spaces", response_model=LearningSpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_learning_space(payload: CreateLearningSpaceRequest, db: Session = Depends(get_db)):
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
        messages = [{"role": "user", "content": payload.content}]
        response_parts: list[str] = []
        async for delta in gateway.stream_text(messages, task="side_agent"):
            response_parts.append(delta)
            yield f"event: message.delta\ndata: {json.dumps({'delta': delta})}\n\n"
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
    note = Note(card_id=card_id, **payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/cards/{card_id}/notes", response_model=list[NoteResponse])
def list_notes(card_id: str, db: Session = Depends(get_db)):
    return list(db.scalars(select(Note).where(Note.card_id == card_id)))
