from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.app.db import Database
from backend.app.gateway import GatewayError, ModelGateway
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


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_falls_back_only_after_retryable_provider_failure(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    model_ids: list[str] = []
    for index, fallback in enumerate((False, True), start=1):
        provider = database.create_model_provider(
            ModelProviderCreate(
                display_name=f"Synthetic Provider {index}",
                base_url=f"https://models-{index}.invalid/v1",
                api_key=SecretStr(f"credential-fixture-{index}"),
                max_retries=0,
            )
        )
        model = database.create_model_profile(
            ModelProfileCreate(
                provider_id=provider["id"],
                display_name=f"Synthetic Model {index}",
                model_name=f"synthetic-model-{index}",
                capabilities={"text"},
                is_fallback=fallback,
            )
        )
        model_ids.append(model["id"])
    database.set_strict_offline(False)
    database.set_project_external_access(project["id"], True)

    def transport(_url: str, payload: bytes, *_args):
        model_name = json.loads(payload)["model"]
        if model_name == "synthetic-model-1":
            return HttpResponse(503, b"{}")
        return success_response("fallback response")

    result = ModelGateway(
        database, OpenAICompatibleAdapter(transport=transport)
    ).complete_external(project["id"], "text", "synthetic fallback prompt")

    assert result["actual_model"] == "synthetic-model-2"
    assert result["fallback_used"] is True
    with database.connect(database.registry_path) as db:
        calls = db.execute(
            """SELECT model_profile_id, status, error_code, route_role,
            fallback_from_model_profile_id FROM model_calls
            WHERE project_id=? ORDER BY rowid""",
            (project["id"],),
        ).fetchall()
    assert [row["status"] for row in calls] == ["failed", "completed"]
    assert calls[0]["error_code"] == "MODEL_SERVICE_UNAVAILABLE"
    assert calls[1]["route_role"] == "fallback"
    assert calls[1]["fallback_from_model_profile_id"] == model_ids[0]

    attempted_models: list[str] = []

    def invalid_credential_transport(_url: str, payload: bytes, *_args):
        attempted_models.append(json.loads(payload)["model"])
        return HttpResponse(401, b"{}")

    with pytest.raises(GatewayError) as captured:
        ModelGateway(
            database, OpenAICompatibleAdapter(transport=invalid_credential_transport)
        ).complete_external(project["id"], "text", "synthetic credential failure")
    assert captured.value.code == "MODEL_CREDENTIAL_INVALID"
    assert attempted_models == ["synthetic-model-1"]


@pytest.mark.skipif(os.name != "nt", reason="Gateway credential resolution uses DPAPI")
def test_gateway_reuses_local_cache_and_can_disable_it(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    provider = database.create_model_provider(
        ModelProviderCreate(
            display_name="Synthetic Cache Provider",
            base_url="https://cache.invalid/v1",
            api_key=SecretStr("credential-fixture"),
        )
    )
    database.create_model_profile(
        ModelProfileCreate(
            provider_id=provider["id"],
            display_name="Synthetic Cache Model",
            model_name="synthetic-cache-model",
            capabilities={"text"},
        )
    )
    database.set_strict_offline(False)
    database.set_project_external_access(project["id"], True)
    transport_calls = 0

    def transport(*_args):
        nonlocal transport_calls
        transport_calls += 1
        return success_response("cached response")

    gateway = ModelGateway(database, OpenAICompatibleAdapter(transport=transport))
    first = gateway.complete_external(
        project["id"], "text", "sensitive cache prompt", evidence_refs=["evidence-1"]
    )
    second = gateway.complete_external(
        project["id"], "text", "sensitive cache prompt", evidence_refs=["evidence-1"]
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["estimated_cost"] == "0"
    assert transport_calls == 1
    assert database.model_cache_entry_count() == 1
    with database.connect(database.registry_path) as db:
        cache = db.execute("SELECT * FROM cache_entries").fetchone()
        cached_call = db.execute(
            "SELECT * FROM model_calls WHERE id=?", (second["call_id"],)
        ).fetchone()
    assert cache["prompt_hash"] != "sensitive cache prompt"
    assert "sensitive cache prompt" not in cache["response_json"]
    assert cache["hit_count"] == 1
    assert cached_call["cache_hit"] == 1

    database.set_model_cache_enabled(False)
    third = gateway.complete_external(
        project["id"], "text", "sensitive cache prompt", evidence_refs=["evidence-1"]
    )
    assert third["cache_hit"] is False
    assert transport_calls == 2
    assert database.clear_model_cache() == 1
    assert database.model_cache_entry_count() == 0
