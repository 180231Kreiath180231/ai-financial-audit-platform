import json
from pathlib import Path

import pytest

from backend.app.assistant import (
    ASSISTANT_PROMPT_VERSION,
    AssistantError,
    AssistantService,
)
from backend.app.db import Database
from backend.app.gateway import ModelGateway
from backend.app.schemas import (
    AssistantMessageCreate,
    AssistantThreadCreate,
    AssistantThreadUpdate,
)
from backend.tests.helpers import create_project


def seed_document(database: Database, root: Path) -> None:
    with database.connect(root / "app.db") as db:
        db.execute(
            """INSERT INTO documents
            (id, filename, sha256, size_bytes, page_count, parse_method,
             parse_version, stored_path, created_at)
            VALUES ('doc-1', '收入截止测试.pdf', ?, 64, 1, 'native_pdf',
                    'v1', 'doc-1.pdf', 'now')""",
            ("a" * 64,),
        )
        db.execute(
            """INSERT INTO pages
            (id, document_id, page_number, block_number, original_text,
             parse_method, parse_version)
            VALUES ('page-1', 'doc-1', 1, 1,
                    '十二月收入确认需要结合签收日期和红冲记录进行截止性测试。',
                    'native_pdf', 'v1')"""
        )


def service_fixture(tmp_path: Path) -> tuple[Database, dict, AssistantService]:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "assistant-project")
    seed_document(database, Path(project["storage_path"]))
    return database, project, AssistantService(database, ModelGateway(database))


def test_assistant_keeps_project_sources_traceable_and_history_opt_in(
    tmp_path: Path,
) -> None:
    database, project, service = service_fixture(tmp_path)
    thread = service.create_thread(project["id"], AssistantThreadCreate())

    updated = service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(
            content="解释十二月收入的截止风险",
            scope="smart",
            preset="explain",
            selected_evidence=[
                {
                    "document_id": "doc-1",
                    "page_number": 1,
                    "block_number": 1,
                    "quote": "十二月收入确认需要结合签收日期和红冲记录进行截止性测试。",
                }
            ],
        ),
    )

    assert updated["title"] == "解释十二月收入的截止风险"
    assert len(updated["messages"]) == 2
    answer = updated["messages"][1]
    assert answer["prompt_version"] == ASSISTANT_PROMPT_VERSION
    assert answer["source_kinds"] == [
        "project_evidence",
        "general_knowledge",
        "local_simulation",
    ]
    assert answer["citations"][0]["document_name"] == "收入截止测试.pdf"
    assert answer["citations"][0]["page_number"] == 1
    assert "本地模拟服务" in answer["content"]

    with database.connect(database.registry_path) as db:
        call = db.execute(
            "SELECT * FROM model_calls WHERE id=?", (answer["model_call_id"],)
        ).fetchone()
    assert call["status"] == "completed"
    assert call["request_summary"] != "解释十二月收入的截止风险"
    scope = json.loads(call["data_scope_json"])
    assert scope["include_history"] is False
    assert scope["internet_access"] is False


def test_general_scope_does_not_read_project_evidence(tmp_path: Path) -> None:
    _, project, service = service_fixture(tmp_path)
    thread = service.create_thread(project["id"], AssistantThreadCreate())

    updated = service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(
            content="什么是审计抽样？",
            scope="general",
            preset="knowledge",
        ),
    )

    answer = updated["messages"][1]
    assert answer["citations"] == []
    assert answer["source_kinds"] == ["general_knowledge", "local_simulation"]
    assert "不会读取其他项目资料" in answer["content"]
    assert "联网检索仍保持关闭" in answer["content"]


def test_project_scope_does_not_fill_source_gaps_with_general_knowledge(
    tmp_path: Path,
) -> None:
    _, project, service = service_fixture(tmp_path)
    thread = service.create_thread(project["id"], AssistantThreadCreate())

    updated = service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(
            content="完全不存在的项目事实 ZXQ-999",
            scope="project",
        ),
    )

    answer = updated["messages"][1]
    assert answer["citations"] == []
    assert answer["source_kinds"] == ["local_simulation"]
    assert "未检索到可复核的项目来源" in answer["content"]
    assert "不会使用通用知识补写项目事实" in answer["content"]


def test_history_is_only_added_when_the_user_opts_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project, service = service_fixture(tmp_path)
    thread = service.create_thread(project["id"], AssistantThreadCreate())
    service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(content="第一问的唯一标记 HISTORY-FIRST", scope="general"),
    )

    prompts: list[str] = []
    original = service.gateway.answer_fake_assistant

    def capture_prompt(project_id: str, **kwargs: object) -> dict:
        prompts.append(str(kwargs["prompt"]))
        return original(project_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service.gateway, "answer_fake_assistant", capture_prompt)
    service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(content="第二问不带历史", scope="general"),
    )
    service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(
            content="第三问显式带历史", scope="general", include_history=True
        ),
    )

    assert "HISTORY-FIRST" not in prompts[0]
    assert "HISTORY-FIRST" in prompts[1]


def test_thread_rename_updates_title_and_is_audited(tmp_path: Path) -> None:
    database, project, service = service_fixture(tmp_path)
    root = Path(project["storage_path"])
    thread = service.create_thread(project["id"], AssistantThreadCreate())

    renamed = service.rename_thread(
        project["id"],
        thread["id"],
        AssistantThreadUpdate(title="  收入截止讨论  "),
    )

    assert renamed["title"] == "收入截止讨论"
    with database.connect(root / "app.db") as db:
        event = db.execute(
            """SELECT details_json FROM audit_events
            WHERE event_type='assistant.thread_renamed' ORDER BY rowid DESC LIMIT 1"""
        ).fetchone()
    details = json.loads(event["details_json"])
    assert details == {
        "thread_id": thread["id"],
        "previous_title": "新对话",
        "title": "收入截止讨论",
    }


def test_selected_scope_rejects_missing_or_tampered_evidence(tmp_path: Path) -> None:
    _, project, service = service_fixture(tmp_path)
    thread = service.create_thread(project["id"], AssistantThreadCreate())

    with pytest.raises(AssistantError) as missing:
        service.send_message(
            project["id"],
            thread["id"],
            AssistantMessageCreate(content="解释证据", scope="selected"),
        )
    assert missing.value.code == "ASSISTANT_EVIDENCE_REQUIRED"

    with pytest.raises(AssistantError) as stale:
        service.send_message(
            project["id"],
            thread["id"],
            AssistantMessageCreate(
                content="解释证据",
                scope="selected",
                selected_evidence=[
                    {
                        "document_id": "doc-1",
                        "page_number": 1,
                        "block_number": 1,
                        "quote": "被篡改的证据内容",
                    }
                ],
            ),
        )
    assert stale.value.code == "ASSISTANT_EVIDENCE_STALE"
    assert service.get_thread(project["id"], thread["id"])["messages"] == []


def test_assistant_message_and_thread_deletion_are_audited(tmp_path: Path) -> None:
    database, project, service = service_fixture(tmp_path)
    root = Path(project["storage_path"])
    thread = service.create_thread(project["id"], AssistantThreadCreate())
    updated = service.send_message(
        project["id"],
        thread["id"],
        AssistantMessageCreate(content="通用问题", scope="general"),
    )
    service.delete_message(project["id"], thread["id"], updated["messages"][0]["id"])
    service.delete_thread(project["id"], thread["id"])

    assert service.list_threads(project["id"]) == []
    with database.connect(root / "app.db") as db:
        events = [
            row["event_type"]
            for row in db.execute(
                """SELECT event_type FROM audit_events
                WHERE event_type LIKE 'assistant.%' ORDER BY rowid"""
            ).fetchall()
        ]
        message_count = db.execute(
            "SELECT COUNT(*) FROM assistant_messages"
        ).fetchone()[0]
    assert events == [
        "assistant.thread_created",
        "assistant.message_created",
        "assistant.message_deleted",
        "assistant.thread_deleted",
    ]
    assert message_count == 0
