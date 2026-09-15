TASK_PROVIDER = {
    "main_agent": "text",
    "side_agent": "text",
    "knowledge_card": "text",
    "bridge_note": "text",
    "note_organizer": "text",
}


def provider_kind_for_task(task: str) -> str:
    return TASK_PROVIDER.get(task, "text")
