"""Prompt-free AI task usage persistence and user-scoped aggregation."""

from datetime import datetime

from sqlalchemy import case, func, select

from ..db import SessionLocal
from ..models import AITaskUsage


def record_usage(**values) -> None:
    """Best-effort persistence; observability must never fail an AI request."""
    try:
        db = SessionLocal()
        try:
            db.add(AITaskUsage(**values))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - explicitly isolated from generation flow
        return


def usage_summary(db, user_id: str, start: datetime | None = None, end: datetime | None = None) -> list[dict]:
    filters = [AITaskUsage.user_id == user_id]
    if start:
        filters.append(AITaskUsage.created_at >= start)
    if end:
        filters.append(AITaskUsage.created_at <= end)
    rows = db.execute(
        select(
            AITaskUsage.task, AITaskUsage.provider_name, AITaskUsage.model_id,
            func.count().label("calls"),
            func.sum(case((AITaskUsage.succeeded.is_(True), 1), else_=0)).label("successes"),
            func.sum(case((AITaskUsage.succeeded.is_(False), 1), else_=0)).label("failures"),
            func.avg(AITaskUsage.duration_ms).label("average_duration_ms"),
            func.sum(AITaskUsage.input_tokens).label("input_tokens"),
            func.sum(AITaskUsage.output_tokens).label("output_tokens"),
            func.sum(AITaskUsage.total_tokens).label("total_tokens"),
        ).where(*filters).group_by(AITaskUsage.task, AITaskUsage.provider_name, AITaskUsage.model_id)
        .order_by(func.count().desc())
    ).mappings()
    return [{
        "task": row["task"], "provider": row["provider_name"], "model": row["model_id"],
        "calls": row["calls"], "successes": row["successes"], "failures": row["failures"],
        "averageDurationMs": round(row["average_duration_ms"] or 0),
        "inputTokens": row["input_tokens"], "outputTokens": row["output_tokens"], "totalTokens": row["total_tokens"],
    } for row in rows]
