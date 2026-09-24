import json
from pathlib import Path

from backend.app.db import Database
from backend.app.worker import (
    CPU_PAUSED_STEP,
    CPU_WAIT_STEP,
    DEFAULT_QUEUE_STEP,
    MEMORY_WAIT_STEP,
    LocalTaskWorker,
)
from backend.tests.helpers import create_project, enqueue, write_pdf


def test_memory_pressure_blocks_new_work_and_explains_wait(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "memory-project")
    root = Path(project["storage_path"])
    incoming = root / "incoming" / "memory.part"
    write_pdf(incoming, "memory")
    task_id = enqueue(database, root, "memory.pdf", incoming)
    sample = [10.0, 71.0]
    now = [0.0]
    worker = LocalTaskWorker(
        database,
        resource_sampler=lambda: (sample[0], sample[1]),
        clock=lambda: now[0],
    )

    worker._observe_resources()
    assert worker._claim_next() is None
    later_source = root / "incoming" / "memory-later.part"
    write_pdf(later_source, "memory-later")
    later_task = enqueue(database, root, "memory-later.pdf", later_source)
    assert worker._claim_next() is None
    with database.connect(root / "app.db") as db:
        blocked = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        blocked_later = db.execute(
            "SELECT * FROM tasks WHERE id=?", (later_task,)
        ).fetchone()
    assert blocked["status"] == "queued"
    assert blocked["current_step"] == MEMORY_WAIT_STEP
    assert blocked_later["current_step"] == MEMORY_WAIT_STEP

    sample[1] = 70.0
    now[0] = 1.0
    worker._observe_resources()
    with database.connect(root / "app.db") as db:
        released = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        events = [
            row["event_type"]
            for row in db.execute("SELECT event_type FROM audit_events ORDER BY created_at")
        ]
    assert released["current_step"] == DEFAULT_QUEUE_STEP
    assert worker._claim_next() == (project["id"], root, task_id)
    assert events == ["resource.memory_blocked", "resource.memory_recovered"]


def test_cpu_guard_pauses_at_safe_point_and_resumes_only_resource_pause(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "cpu-project")
    root = Path(project["storage_path"])
    resource_source = root / "incoming" / "resource.part"
    user_source = root / "incoming" / "user.part"
    queued_source = root / "incoming" / "queued.part"
    write_pdf(resource_source, "resource")
    write_pdf(user_source, "user")
    write_pdf(queued_source, "queued")
    resource_task = enqueue(database, root, "resource.pdf", resource_source)
    user_task = enqueue(database, root, "user.pdf", user_source)
    queued_task = enqueue(database, root, "queued.pdf", queued_source)
    with database.connect(root / "app.db") as db:
        db.execute(
            """UPDATE tasks SET status='paused', pause_reason='user',
            current_step='已在安全点暂停' WHERE id=?""",
            (user_task,),
        )

    sample = [80.0, 40.0]
    now = [0.0]
    worker = LocalTaskWorker(
        database,
        resource_sampler=lambda: (sample[0], sample[1]),
        clock=lambda: now[0],
    )
    assert worker._claim_next() == (project["id"], root, resource_task)

    worker._observe_resources()
    now[0] = 10.0
    worker._observe_resources()
    with database.connect(root / "app.db") as db:
        pausing = db.execute(
            "SELECT * FROM tasks WHERE id=?", (resource_task,)
        ).fetchone()
        waiting = db.execute("SELECT * FROM tasks WHERE id=?", (queued_task,)).fetchone()
    assert pausing["status"] == "pausing"
    assert pausing["pause_reason"] == "resource"
    assert waiting["current_step"] == CPU_WAIT_STEP
    assert worker._claim_next() is None

    assert worker._safe_point(root, resource_task, resource_source) is False
    with database.connect(root / "app.db") as db:
        paused = db.execute("SELECT * FROM tasks WHERE id=?", (resource_task,)).fetchone()
    assert paused["status"] == "paused"
    assert paused["current_step"] == CPU_PAUSED_STEP

    sample[0] = 20.0
    now[0] = 11.0
    worker._observe_resources()
    now[0] = 21.0
    worker._observe_resources()
    with database.connect(root / "app.db") as db:
        resource_resumed = db.execute(
            "SELECT * FROM tasks WHERE id=?", (resource_task,)
        ).fetchone()
        user_paused = db.execute("SELECT * FROM tasks WHERE id=?", (user_task,)).fetchone()
        audit_rows = db.execute(
            "SELECT event_type, details_json FROM audit_events ORDER BY created_at"
        ).fetchall()
    assert resource_resumed["status"] == "queued"
    assert resource_resumed["pause_reason"] is None
    assert user_paused["status"] == "paused"
    assert user_paused["pause_reason"] == "user"
    assert {row["event_type"] for row in audit_rows} >= {
        "task.resource_pause_requested",
        "task.paused",
        "task.resource_resumed",
    }
    paused_event = next(row for row in audit_rows if row["event_type"] == "task.paused")
    assert json.loads(paused_event["details_json"])["pause_reason"] == "resource"


def test_restart_requeues_resource_pause_but_preserves_user_pause(tmp_path: Path) -> None:
    data_dir = tmp_path / "registry"
    database = Database(data_dir)
    project = create_project(database, tmp_path / "restart-project")
    root = Path(project["storage_path"])
    resource_source = root / "incoming" / "restart-resource.part"
    user_source = root / "incoming" / "restart-user.part"
    write_pdf(resource_source, "restart-resource")
    write_pdf(user_source, "restart-user")
    resource_task = enqueue(database, root, "restart-resource.pdf", resource_source)
    user_task = enqueue(database, root, "restart-user.pdf", user_source)
    with database.connect(root / "app.db") as db:
        db.execute(
            "UPDATE tasks SET status='paused', pause_reason='resource' WHERE id=?",
            (resource_task,),
        )
        db.execute(
            "UPDATE tasks SET status='paused', pause_reason='user' WHERE id=?",
            (user_task,),
        )

    restarted = Database(data_dir)
    restarted.recover_tasks()

    with restarted.connect(root / "app.db") as db:
        resource = db.execute(
            "SELECT * FROM tasks WHERE id=?", (resource_task,)
        ).fetchone()
        user = db.execute("SELECT * FROM tasks WHERE id=?", (user_task,)).fetchone()
    assert resource["status"] == "queued"
    assert resource["pause_reason"] is None
    assert user["status"] == "paused"
    assert user["pause_reason"] == "user"
