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
    TaskDefinition("course_intake", "课程需求澄清", "conversation"),
    TaskDefinition("course_intake_state", "课程需求步骤澄清", "conversation"),
    TaskDefinition("course_outline", "课程大纲生成", "generation"),
    TaskDefinition("course_outline_revision", "课程大纲修订", "conversation"),
    TaskDefinition("course_plan", "课程规划", "generation"),
    TaskDefinition("section_content", "章节内容生成", "generation"),
    TaskDefinition("section_summary", "章节摘要生成", "utility"),
    TaskDefinition("section_review", "章节质量审查", "quality"),
    TaskDefinition("section_repair", "章节内容修订", "quality"),
    TaskDefinition("course_review", "课程整体质量审查", "quality"),
    TaskDefinition("course_targeted_repair", "课程定点修复", "generation"),
    TaskDefinition("quiz_generation", "理解检查生成", "generation"),
    TaskDefinition("quiz_evaluation", "理解检查评估", "assessment"),
    TaskDefinition("teacher_guidance", "导师引导", "teaching"),
    TaskDefinition("side_answer", "答疑回复", "conversation"),
    TaskDefinition("side_answer_plan", "答疑规划", "conversation"),
    TaskDefinition("gap_diagnosis", "知识断层诊断", "diagnosis"),
    # Legacy route kept so existing settings can be migrated at runtime.
    TaskDefinition("side_agent", "旧版答疑与诊断", "compatibility"),
    # Legacy route kept so existing settings can be migrated at runtime.
    TaskDefinition("knowledge_card", "旧版知识卡生成", "compatibility"),
    TaskDefinition("bridge_note", "知识桥接", "generation"),
    TaskDefinition("conversation_title", "会话标题", "utility"),
    TaskDefinition("group_director", "多角色调度", "orchestration"),
)

TASK_BY_ID = {task.id: task for task in TASKS}


def is_known_task(task: str) -> bool:
    return task in TASK_BY_ID
