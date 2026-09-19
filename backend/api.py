from fastapi import APIRouter, Depends

from .agents.registry import AGENTS
from .schemas import AgentDefinitionResponse
from .security.auth import require_current_user
from .services.provider_settings import restore_active_provider

router = APIRouter(dependencies=[Depends(require_current_user)])
public_router = APIRouter()

"""Learning-domain routes."""

@public_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents():
    return AGENTS
