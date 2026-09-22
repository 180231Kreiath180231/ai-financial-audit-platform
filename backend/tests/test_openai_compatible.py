from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.app.db import Database
from backend.app.gateway import ModelGateway
from backend.app.openai_compatible import (
    HttpResponse,
    OpenAICompatibleAdapter,
    ProviderRequestError,
)
from backend.app.schemas import ModelProfileCreate, ModelProviderCreate
from backend.tests.helpers import create_project


def success_response(content: str = "synthetic response") -> HttpResponse:
    return HttpResponse(
        status=200,
        body=json.dumps(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            }
        ).encode(),
    )


def test_adapter_sends_openai_compatible_request_without_logging_secret() -> None:
    captured: dict = {}

    def transport(url: str, payload: bytes, headers: dict[str, str], timeout: int):
        captured.update(url=url, payload=json.loads(payload), headers=headers, timeout=timeout)
        return success_response()

    result = OpenAICompatibleAdapter(transport=transport).complete(
        base_url="https://models.invalid/v1/",
        api_key="credential-fixture",
        default_headers={"X-Tenant": "synthetic"},
        model_name="text-model",
        prompt="synthetic prompt",
        timeout_seconds=12,
        max_retries=1,
    )

    assert captured["url"] == "https://models.invalid/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer credential-fixture"
    assert captured["headers"]["X-Tenant"] == "synthetic"
    assert captured["payload"]["model"] == "text-model"
    assert result.input_tokens == 120
    assert result.output_tokens == 30


def test_adapter_retries_rate_limit_and_records_retry_count() -> None:
    responses = [HttpResponse(429, b"{}"), success_response()]
    delays: list[float] = []

    def transport(*_args):
        return responses.pop(0)

    result = OpenAICompatibleAdapter(transport=transport, sleep=delays.append).complete(
        base_url="https://models.invalid/v1",
        api_key="fixture",
        default_headers={},
        model_name="text-model",
        prompt="synthetic",
        timeout_seconds=10,
        max_retries=2,
    )

    assert result.retry_count == 1
    assert delays == [1]


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (HttpResponse(401, b"{}"), "MODEL_CREDENTIAL_INVALID"),
        (HttpResponse(402, b"{}"), "MODEL_BALANCE_INSUFFICIENT"),
        (HttpResponse(200, b"not-json"), "MODEL_RESPONSE_INVALID_JSON"),
        (HttpResponse(200, b"{}"), "MODEL_RESPONSE_SCHEMA_INVALID"),
    ],
)
def test_adapter_maps_actionable_errors(response: HttpResponse, expected_code: str) -> None:
    adapter = OpenAICompatibleAdapter(transport=lambda *_args: response)

    with pytest.raises(ProviderRequestError) as captured:
        adapter.complete(
            base_url="https://models.invalid/v1",
            api_key="fixture",
            default_headers={},
            model_name="text-model",
            prompt="synthetic",
            timeout_seconds=10,
            max_retries=0,
        )

    assert captured.value.code == expected_code


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_external_completion_is_gated_and_audited(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    provider = database.create_model_provider(
        ModelProviderCreate(
            display_name="Synthetic Provider",
            base_url="https://models.invalid/v1",
            api_key=SecretStr("credential-fixture"),
        )
    )
    database.create_model_profile(
        ModelProfileCreate(
            provider_id=provider["id"],
            display_name="Synthetic Model",
            model_name="synthetic-model",
            capabilities={"text"},
            input_cost_per_million="1.5",
            output_cost_per_million="6",
        )
    )
    database.set_strict_offline(False)
    database.set_project_external_access(project["id"], True)
    adapter = OpenAICompatibleAdapter(transport=lambda *_args: success_response())

    result = ModelGateway(database, adapter).complete_external(
        project["id"], "text", "sensitive fixture prompt", evidence_refs=["evidence-1"]
    )

    assert result["actual_model"] == "synthetic-model"
    assert result["estimated_cost"] == "0.00036"
    with database.connect(database.registry_path) as db:
        call = db.execute("SELECT * FROM model_calls WHERE id=?", (result["call_id"],)).fetchone()
    assert call["status"] == "completed"
    assert call["input_tokens"] == 120
    assert call["output_tokens"] == 30
    assert call["evidence_refs_json"] == '["evidence-1"]'
    assert call["request_summary"] != "sensitive fixture prompt"
