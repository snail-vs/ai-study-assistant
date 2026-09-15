from .prompts import MAIN_AGENT_SYSTEM
from .schemas import KnowledgeCardDraft
from ..ai.gateway import AIGateway


class MainAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def create_card(self, goal: str) -> KnowledgeCardDraft:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": MAIN_AGENT_SYSTEM},
                {"role": "user", "content": goal},
            ],
            task="knowledge_card",
            schema=KnowledgeCardDraft.model_json_schema(),
        )
        return KnowledgeCardDraft.model_validate(result)
