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
    AgentDefinition("teacher", "课程导师", "teacher", "负责章节导入、学习路径归位和教学连接。", priority=10),
    AgentDefinition("side_tutor", "答疑助教", "assistant", "对当前问题给出最小充分回答。", priority=7),
    AgentDefinition("peer_curiosity", "好奇同学", "student", "提出初学者视角的追问，帮助发现盲点。", priority=5),
    AgentDefinition("peer_challenger", "质疑同学", "student", "提出反例和边界条件，促进深入思考。", priority=4),
    AgentDefinition("diagnostician", "学习诊断器", "diagnostician", "判断理解状态和前置知识断层。", visible=False),
    AgentDefinition("assessment", "测评智能体", "assessment", "生成理解检查并评估学习结果。", visible=False),
    AgentDefinition("recommendation", "前置知识推荐器", "recommendation", "生成和管理前置知识建议。", visible=False),
)

AGENTS_BY_ID = {agent.id: agent for agent in AGENTS}


def default_participants(conversation_type: str) -> list[str]:
    return ["teacher"] if conversation_type == "main" else ["side_tutor"]


def get_agent(agent_id: str) -> AgentDefinition | None:
    return AGENTS_BY_ID.get(agent_id)
