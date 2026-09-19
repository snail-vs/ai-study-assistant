"""Application workflows for related-card proposals."""

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..agents.bridge_agent import BridgeAgent
from ..agents.main_agent import MainAgent
from ..models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    RelatedCardProposal,
)
from .ownership import owned_card
from .provider_settings import restore_active_provider


RELATION_LABELS = {
    "prerequisite": "前置知识",
    "deep_dive": "深入理解",
    "application": "应用延展",
}


def relation_label(relation_type: str | None) -> str:
    return RELATION_LABELS.get(relation_type or "prerequisite", "学习分支")


async def accept_proposal(proposal_id: str, db: Session):
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
    bridge = await BridgeAgent(restore_active_provider(db)).create(source_card.title, card.title)
    db.add(BridgeNote(card_id=source_card.id, related_card_id=card.id, content=bridge.content))
    proposal.status = "accepted"
    proposal.generated_card_id = card.id
    db.commit()
    db.refresh(card)
    return card


def start_proposal_discussion(proposal_id: str, db: Session):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    if proposal.generated_card_id:
        raise HTTPException(status_code=400, detail="Proposal has already been accepted")
    section = db.get(CardSection, proposal.section_id) if proposal.section_id else None
    if not section or section.card_id != proposal.card_id:
        raise HTTPException(
            status_code=409,
            detail="Proposal is not associated with a valid course section",
        )
    conversation = Conversation(
        card_id=proposal.card_id,
        section_id=proposal.section_id,
        conversation_type="side",
        title=f"讨论：{proposal.title}",
        root_question=(
            f"推荐学习主题：{proposal.title}\n"
            f"推荐原因：{proposal.reason}\n"
            f"请围绕这个{relation_label(proposal.relation_type)}建议"
            "帮助我判断是否值得创建一条学习分支。"
        ),
    )
    db.add(conversation)
    proposal.status = "discussing"
    db.commit()
    db.refresh(conversation)
    return conversation


def reject_proposal(proposal_id: str, db: Session):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    proposal.status = "rejected"
    db.commit()
    return {"status": "rejected", "proposalId": proposal_id}
