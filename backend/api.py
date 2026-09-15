import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai.gateway import AIGateway
from .db import get_db
from .models import Conversation, KnowledgeCard, LearningSpace, Note
from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    CreateLearningSpaceRequest,
    CreateNoteRequest,
    LearningSpaceList,
    LearningSpaceResponse,
    NoteResponse,
)

router = APIRouter()
gateway = AIGateway()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/learning-spaces", response_model=LearningSpaceResponse, status_code=status.HTTP_201_CREATED)
def create_learning_space(payload: CreateLearningSpaceRequest, db: Session = Depends(get_db)):
    space = LearningSpace(title=payload.title, learning_goal=payload.learning_goal)
    db.add(space)
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


@router.get("/cards/{card_id}")
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
async def stream_message(conversation_id: str, payload: dict[str, str], db: Session = Depends(get_db)) -> StreamingResponse:
    if not db.get(Conversation, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def events() -> AsyncIterator[str]:
        yield f"event: message.started\ndata: {json.dumps({'conversationId': conversation_id})}\n\n"
        messages = [{"role": "user", "content": payload.get("content", "")}]
        async for delta in gateway.stream_text(messages, task="side_agent"):
            yield f"event: message.delta\ndata: {json.dumps({'delta': delta})}\n\n"
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
