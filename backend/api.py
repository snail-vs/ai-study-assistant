import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .db import get_db
from .models import CardSection, Conversation, KnowledgeCard, LearningSpace, Message, Note
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
)

router = APIRouter()
gateway = AIGateway()
side_agent = SideAgent(gateway)
main_agent = MainAgent(gateway)


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
                    proposal["proposalId"] = str(uuid4())
                    yield f"event: related_card.proposed\ndata: {json.dumps(proposal, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_DIAGNOSIS_FAILED', 'message': str(exc)})}\n\n"
        yield "event: message.completed\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


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
