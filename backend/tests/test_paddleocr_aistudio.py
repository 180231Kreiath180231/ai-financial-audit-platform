from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.app.db import Database
from backend.app.gateway import GatewayError, ModelGateway
from backend.app.paddleocr_aistudio import (
    MAX_PAGE_BYTES,
    PADDLEOCR_JOB_URL,
    PaddleOcrAiStudioAdapter,
    PaddleOcrHttpRequest,
    PaddleOcrHttpResponse,
    PaddleOcrRequestError,
)
from backend.app.schemas import ModelProfileCreate, ModelProviderCreate
from backend.tests.helpers import create_project


def response(payload: object, status: int = 200) -> PaddleOcrHttpResponse:
    return PaddleOcrHttpResponse(status=status, body=json.dumps(payload).encode())


def test_adapter_submits_one_png_polls_and_reads_text_only(tmp_path: Path) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"synthetic-png")
    requests: list[PaddleOcrHttpRequest] = []
    replies = [
        response({"data": {"jobId": "job-synthetic-1"}}),
        response({"data": {"state": "pending"}}),
        response(
            {
                "data": {
                    "state": "done",
                    "extractProgress": {"extractedPages": 1},
                    "resultUrl": {"jsonUrl": "https://results.invalid/job.jsonl"},
                }
            }
        ),
        PaddleOcrHttpResponse(
            status=200,
            body=(
                b'{"result":{"layoutParsingResults":[{"markdown":'
                b'{"text":"Synthetic OCR text ![chart](https://ignored/image.png)",'
                b'"images":{"ignored.png":"https://ignored"}},'
                b'"outputImages":{"page":"https://ignored"}}]}}\n'
            ),
        ),
    ]

    def transport(request: PaddleOcrHttpRequest) -> PaddleOcrHttpResponse:
        requests.append(request)
        return replies.pop(0)

    validated: list[str] = []
    result = PaddleOcrAiStudioAdapter(
        transport=transport,
        sleep=lambda _seconds: None,
        result_url_validator=validated.append,
        poll_interval_seconds=0,
    ).analyze_page(
        job_url=PADDLEOCR_JOB_URL,
        access_token="credential-fixture",
        default_headers={
            "X-Synthetic": "true",
            "Authorization": "must-not-override-token",
            "Content-Type": "must-not-break-multipart",
        },
        model_name="PaddleOCR-VL-1.6",
        page_path=page,
        timeout_seconds=20,
        max_retries=0,
        should_continue=lambda: True,
    )

    assert result.recognized_text == "Synthetic OCR text chart"
    assert result.job_id == "job-synthetic-1"
    assert result.extracted_pages == 1
    assert result.remote_cleanup_status == "unsupported"
    assert requests[0].method == "POST"
    assert requests[0].file_path == page
    assert requests[0].fields == {
        "model": "PaddleOCR-VL-1.6",
        "optionalPayload": (
            '{"useDocOrientationClassify":false,"useDocUnwarping":false,'
            '"useChartRecognition":false}'
        ),
    }
    assert requests[0].headers["Authorization"] == "bearer credential-fixture"
    assert "Content-Type" not in requests[0].headers
    assert requests[-1].headers == {"Accept": "application/x-ndjson, application/json"}
    assert validated == ["https://results.invalid/job.jsonl"]
    assert len(requests) == 4


def test_adapter_retries_rate_limit_without_resubmitting_after_job_creation(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"synthetic-png")
    replies = [
        response({}, 429),
        response({"data": {"jobId": "job-2"}}),
        response(
            {
                "data": {
                    "state": "done",
                    "resultUrl": {"jsonUrl": "https://results.invalid/job-2.jsonl"},
                }
            }
        ),
        PaddleOcrHttpResponse(
            200,
            b'{"result":{"layoutParsingResults":[{"markdown":{"text":"ok"}}]}}',
        ),
    ]
    delays: list[float] = []

    result = PaddleOcrAiStudioAdapter(
        transport=lambda _request: replies.pop(0),
        sleep=delays.append,
        result_url_validator=lambda _url: None,
    ).analyze_page(
        job_url=PADDLEOCR_JOB_URL,
        access_token="fixture",
        default_headers={},
        model_name="PaddleOCR-VL-1.6",
        page_path=page,
        timeout_seconds=20,
        max_retries=1,
        should_continue=lambda: True,
    )

    assert result.retry_count == 1
    assert delays == [1]


@pytest.mark.parametrize(
    ("reply", "expected_code"),
    [
        (response({}, 401), "OCR_CREDENTIAL_INVALID"),
        (response({}, 402), "OCR_BALANCE_INSUFFICIENT"),
        (PaddleOcrHttpResponse(200, b"not-json"), "OCR_RESPONSE_INVALID_JSON"),
        (response({"data": {}}), "OCR_RESPONSE_SCHEMA_INVALID"),
    ],
)
def test_adapter_maps_actionable_submission_errors(
    tmp_path: Path, reply: PaddleOcrHttpResponse, expected_code: str
) -> None:
    page = tmp_path / "page.png"
    page.write_bytes(b"synthetic")
    adapter = PaddleOcrAiStudioAdapter(
        transport=lambda _request: reply,
        result_url_validator=lambda _url: None,
    )

    with pytest.raises(PaddleOcrRequestError) as captured:
        adapter.analyze_page(
            job_url=PADDLEOCR_JOB_URL,
            access_token="fixture",
            default_headers={},
            model_name="PaddleOCR-VL-1.6",
            page_path=page,
            timeout_seconds=20,
            max_retries=0,
            should_continue=lambda: True,
        )

    assert captured.value.code == expected_code


def test_adapter_stops_polling_at_local_safe_point(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    page.write_bytes(b"synthetic")
    replies = [response({"data": {"jobId": "job-3"}})]
    adapter = PaddleOcrAiStudioAdapter(
        transport=lambda _request: replies.pop(0),
        result_url_validator=lambda _url: None,
    )

    with pytest.raises(PaddleOcrRequestError) as captured:
        adapter.analyze_page(
            job_url=PADDLEOCR_JOB_URL,
            access_token="fixture",
            default_headers={},
            model_name="PaddleOCR-VL-1.6",
            page_path=page,
            timeout_seconds=20,
            max_retries=0,
            should_continue=lambda: False,
        )

    assert captured.value.code == "OCR_TASK_INTERRUPTED"
    assert captured.value.remote_request_id == "job-3"
    assert captured.value.remote_cleanup_status == "unsupported"


def test_adapter_rejects_oversized_page_before_transport(tmp_path: Path) -> None:
    page = tmp_path / "large-page.png"
    with page.open("wb") as output:
        output.truncate(MAX_PAGE_BYTES + 1)
    calls = 0

    def transport(_request: PaddleOcrHttpRequest) -> PaddleOcrHttpResponse:
        nonlocal calls
        calls += 1
        return response({})

    adapter = PaddleOcrAiStudioAdapter(transport=transport)
    with pytest.raises(PaddleOcrRequestError) as captured:
        adapter.analyze_page(
            job_url=PADDLEOCR_JOB_URL,
            access_token="fixture",
            default_headers={},
            model_name="PaddleOCR-VL-1.6",
            page_path=page,
            timeout_seconds=20,
            max_retries=0,
            should_continue=lambda: True,
        )

    assert captured.value.code == "OCR_PAGE_TOO_LARGE"
    assert captured.value.external_request is False
    assert captured.value.remote_cleanup_status == "not_applicable"
    assert calls == 0


def configured_gateway(
    tmp_path: Path,
    adapter: PaddleOcrAiStudioAdapter,
    *,
    synthetic: bool = True,
) -> tuple[Database, dict, ModelGateway]:
    database = Database(tmp_path / "registry")
    project = create_project(
        database,
        tmp_path / "project",
        is_synthetic=synthetic,
    )
    provider = database.create_model_provider(
        ModelProviderCreate(
            provider_kind="paddleocr_aistudio",
            display_name="PaddleOCR Synthetic",
            base_url=PADDLEOCR_JOB_URL,
            api_key=SecretStr("credential-fixture"),
        )
    )
    database.create_model_profile(
        ModelProfileCreate(
            provider_id=provider["id"],
            display_name="PaddleOCR VL 1.6",
            model_name="PaddleOCR-VL-1.6",
            capabilities={"vision", "file_upload"},
        )
    )
    database.set_strict_offline(False)
    database.set_project_external_access(project["id"], True)
    return database, project, ModelGateway(database, paddleocr_adapter=adapter)


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_audits_minimal_page_scope_and_remote_lifecycle(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    page.write_bytes(b"synthetic")
    replies = [
        response({"data": {"jobId": "job-audit"}}),
        response(
            {
                "data": {
                    "state": "done",
                    "resultUrl": {"jsonUrl": "https://results.invalid/job.jsonl"},
                }
            }
        ),
        PaddleOcrHttpResponse(
            200,
            b'{"result":{"layoutParsingResults":[{"markdown":{"text":"audited"}}]}}',
        ),
    ]
    adapter = PaddleOcrAiStudioAdapter(
        transport=lambda _request: replies.pop(0),
        result_url_validator=lambda _url: None,
    )
    database, project, gateway = configured_gateway(tmp_path, adapter)

    result = gateway.analyze_paddleocr_page(
        project["id"],
        task_id="task-synthetic",
        document_name="sensitive-filename.pdf",
        page_number=2,
        image_path=page,
        image_sha256="a" * 64,
        width=100,
        height=200,
        should_continue=lambda: True,
    )

    assert result["external_request"] is True
    assert result["remote_request_id"] == "job-audit"
    assert result["remote_cleanup_status"] == "unsupported"
    with database.connect(database.registry_path) as db:
        call = db.execute("SELECT * FROM model_calls WHERE id=?", (result["call_id"],)).fetchone()
    assert call["status"] == "completed"
    assert call["task_id"] == "task-synthetic"
    assert call["remote_request_id"] == "job-audit"
    assert call["remote_cleanup_status"] == "unsupported"
    assert json.loads(call["data_scope_json"])["whole_document"] is False
    assert "sensitive-filename.pdf" not in call["data_scope_json"]
    assert "credential-fixture" not in str(dict(call))


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_audits_remote_job_when_local_task_is_interrupted(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    page.write_bytes(b"synthetic")
    adapter = PaddleOcrAiStudioAdapter(
        transport=lambda _request: response({"data": {"jobId": "job-interrupted"}}),
        result_url_validator=lambda _url: None,
    )
    database, project, gateway = configured_gateway(tmp_path, adapter)

    with pytest.raises(GatewayError) as captured:
        gateway.analyze_paddleocr_page(
            project["id"],
            task_id="task-interrupted",
            document_name="synthetic.pdf",
            page_number=1,
            image_path=page,
            image_sha256="c" * 64,
            width=100,
            height=100,
            should_continue=lambda: False,
        )

    assert captured.value.code == "OCR_TASK_INTERRUPTED"
    assert captured.value.external_request is True
    assert captured.value.remote_request_id == "job-interrupted"
    assert captured.value.remote_cleanup_status == "unsupported"
    with database.connect(database.registry_path) as db:
        call = db.execute(
            "SELECT status, remote_request_id, remote_cleanup_status "
            "FROM model_calls WHERE task_id='task-interrupted'"
        ).fetchone()
    assert tuple(call) == ("cancelled", "job-interrupted", "unsupported")


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_blocks_real_project_before_paddleocr_transport(tmp_path: Path) -> None:
    calls = 0

    def transport(_request: PaddleOcrHttpRequest) -> PaddleOcrHttpResponse:
        nonlocal calls
        calls += 1
        return response({})

    database, project, gateway = configured_gateway(
        tmp_path,
        PaddleOcrAiStudioAdapter(transport=transport),
        synthetic=False,
    )
    page = tmp_path / "page.png"
    page.write_bytes(b"synthetic")

    with pytest.raises(GatewayError) as captured:
        gateway.analyze_paddleocr_page(
            project["id"],
            task_id="task-real",
            document_name="real.pdf",
            page_number=1,
            image_path=page,
            image_sha256="b" * 64,
            width=100,
            height=100,
            should_continue=lambda: True,
        )

    assert captured.value.code == "OCR_REMOTE_RETENTION_UNVERIFIED"
    assert calls == 0
    with database.connect(database.registry_path) as db:
        audit = db.execute(
            "SELECT status, error_code FROM model_calls WHERE task_id='task-real'"
        ).fetchone()
    assert tuple(audit) == ("blocked", "OCR_REMOTE_RETENTION_UNVERIFIED")
