from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    role: str
    description: str
    visible: bool = True
    priority: int = 5


AGENTS = (
    AgentDefinition("teacher", "老师", "teacher", "负责章节引导、主线归位和教学总结。", priority=10),
    AgentDefinition("side_tutor", "旁支助教", "assistant", "回答当前问题，补充概念和例子。", priority=7),
    AgentDefinition("peer_curiosity", "好奇同学", "student", "提出初学者视角的追问，帮助发现盲点。", priority=5),
    AgentDefinition("peer_challenger", "质疑同学", "student", "提出反例和边界条件，促进深入思考。", priority=4),
    AgentDefinition("diagnostician", "学习诊断", "diagnostician", "判断理解状态和知识断层。", visible=False),
    AgentDefinition("recommendation", "学习推荐", "recommendation", "生成和管理知识断层推荐。", visible=False),
)

AGENTS_BY_ID = {agent.id: agent for agent in AGENTS}


def default_participants(conversation_type: str) -> list[str]:
    return ["teacher"] if conversation_type == "main" else ["side_tutor"]


def get_agent(agent_id: str) -> AgentDefinition | None:
    return AGENTS_BY_ID.get(agent_id)
