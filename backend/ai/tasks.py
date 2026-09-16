"""Stable task taxonomy used for model routing.

Tasks describe work being performed, while agents describe who performs it.
Keeping these dimensions separate lets one agent use different models for
course generation, teaching guidance, and quick side answers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    label: str
    category: str


TASKS = (
    TaskDefinition("knowledge_card", "生成知识卡", "generation"),
    TaskDefinition("teacher_guidance", "导师引导", "teaching"),
    TaskDefinition("side_answer", "答疑回复", "conversation"),
    TaskDefinition("gap_diagnosis", "知识断层诊断", "diagnosis"),
    # Legacy route kept so existing settings can be migrated at runtime.
    TaskDefinition("side_agent", "旧版答疑与诊断", "compatibility"),
    TaskDefinition("bridge_note", "知识桥接", "generation"),
    TaskDefinition("conversation_title", "会话标题", "utility"),
    TaskDefinition("group_director", "多角色调度", "orchestration"),
)

TASK_BY_ID = {task.id: task for task in TASKS}


def is_known_task(task: str) -> bool:
    return task in TASK_BY_ID
