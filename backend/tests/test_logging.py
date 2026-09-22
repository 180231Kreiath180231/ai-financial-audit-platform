import json
import logging

from backend.app.logging_config import JsonFormatter


def test_structured_log_contains_auditable_fields() -> None:
    record = logging.LogRecord(
        name="hengjian.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="task.completed",
        args=(),
        exc_info=None,
    )
    record.project_id = "project-synthetic"
    record.task_id = "task-synthetic"
    record.status = "completed"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "task.completed"
    assert payload["project_id"] == "project-synthetic"
    assert payload["task_id"] == "task-synthetic"
    assert payload["status"] == "completed"
    assert "timestamp" in payload
