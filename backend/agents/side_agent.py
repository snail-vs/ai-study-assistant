from .prompts import SIDE_AGENT_SYSTEM
from .schemas import SideAgentResult
from ..ai.gateway import AIGateway


class SideAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def diagnose(self, question: str, context: str = "") -> SideAgentResult:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": SIDE_AGENT_SYSTEM},
                {"role": "user", "content": f"当前内容：{context}\n用户问题：{question}"},
            ],
            task="side_agent",
            schema=SideAgentResult.model_json_schema(by_alias=True),
        )
        return SideAgentResult.model_validate(result)
