import logging

from pydantic import ValidationError

from .prompts import SIDE_AGENT_SYSTEM
from .schemas import SideAgentResult
from ..ai.gateway import AIGateway


logger = logging.getLogger("studycenter.ai.side_agent")


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
        try:
            return SideAgentResult.model_validate(result)
        except ValidationError:
            # A malformed optional recommendation must not invalidate the
            # answer the learner already received. Keep the diagnosis and
            # answer, but omit the unusable recommendation.
            if isinstance(result, dict) and isinstance(result.get("proposal"), dict):
                proposal = result["proposal"]
                title = proposal.get("title") or proposal.get("topic") or proposal.get("name")
                reason = proposal.get("reason") or proposal.get("description") or proposal.get("content")
                if title and reason:
                    result["proposal"] = {"title": title, "reason": reason}
                else:
                    logger.warning("Discarding malformed side-agent proposal: %s", proposal)
                    result["proposal"] = None
                return SideAgentResult.model_validate(result)
            raise
