from ..ai.gateway import AIGateway
from .prompts import BRIDGE_AGENT_SYSTEM
from .schemas import BridgeNoteDraft


class BridgeAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def create(self, main_title: str, related_title: str) -> BridgeNoteDraft:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": BRIDGE_AGENT_SYSTEM},
                {"role": "user", "content": f"来源知识卡：{main_title}\n学习分支知识卡：{related_title}"},
            ],
            task="bridge_note",
            schema=BridgeNoteDraft.model_json_schema(),
        )
        return BridgeNoteDraft.model_validate(result)
