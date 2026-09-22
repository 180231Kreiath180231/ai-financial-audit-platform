from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.app.db import Database
from backend.app.gateway import GatewayError, ModelGateway
from backend.app.schemas import ModelProfileCreate, ModelProviderCreate
from backend.tests.helpers import create_project


def add_external_text_model(database: Database) -> None:
    provider = database.create_model_provider(
        ModelProviderCreate(
            display_name="Synthetic OpenAI-compatible",
            base_url="https://models.invalid/v1",
        )
    )
    database.create_model_profile(
        ModelProfileCreate(
            provider_id=provider["id"],
            display_name="Synthetic Text",
            model_name="synthetic-text-v1",
            capabilities={"text", "json_schema"},
        )
    )


def test_fake_probe_routes_by_capability_and_audits_without_prompt(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")

    result = ModelGateway(database).probe(project["id"], "vision", "synthetic secret marker")

    assert result["actual_model"] == "fake-structured-v1"
    assert result["external_request"] is False
    with database.connect(database.registry_path) as db:
        call = db.execute("SELECT * FROM model_calls WHERE id=?", (result["call_id"],)).fetchone()
    assert call["status"] == "completed"
    assert call["request_summary"] != "synthetic secret marker"
    assert len(call["request_summary"]) == 64


@pytest.mark.parametrize(
    ("strict_offline", "project_access", "expected_code"),
    [
        (True, True, "OFFLINE_MODE_BLOCKED"),
        (False, False, "PROJECT_EXTERNAL_ACCESS_REQUIRED"),
    ],
)
def test_external_route_requires_both_global_and_project_consent(
    tmp_path: Path,
    strict_offline: bool,
    project_access: bool,
    expected_code: str,
) -> None:
    database = Database(tmp_path / "registry")
    project = create_project(database, tmp_path / "project")
    add_external_text_model(database)
    database.set_strict_offline(strict_offline)
    database.set_project_external_access(project["id"], project_access)
    with database.connect(database.registry_path) as db:
        db.execute("UPDATE model_providers SET enabled=0 WHERE id='fake-provider'")

    with pytest.raises(GatewayError) as captured:
        ModelGateway(database).probe(project["id"], "text", "must not leave device")

    assert captured.value.code == expected_code
    with database.connect(database.registry_path) as db:
        call = db.execute("SELECT * FROM model_calls ORDER BY started_at DESC LIMIT 1").fetchone()
    assert call["status"] == "blocked"
    assert call["error_code"] == expected_code
    assert call["request_summary"] != "must not leave device"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is a Windows security boundary")
def test_api_key_uses_dpapi_reference_and_never_enters_sqlite(tmp_path: Path) -> None:
    database = Database(tmp_path / "registry")
    raw_secret = "synthetic-test-key-not-real"

    provider = database.create_model_provider(
        ModelProviderCreate(
            display_name="Credential Test",
            base_url="https://credentials.invalid/v1",
            api_key=SecretStr(raw_secret),
        )
    )

    assert provider["secret_configured"] is True
    registry_bytes = database.registry_path.read_bytes()
    assert raw_secret.encode() not in registry_bytes
    secret_files = list((database.data_dir / "secrets").glob("*.bin"))
    assert len(secret_files) == 1
    assert raw_secret.encode() not in secret_files[0].read_bytes()
    with database.connect(database.registry_path) as db:
        reference = db.execute(
            "SELECT api_key_ref FROM model_providers WHERE id=?", (provider["id"],)
        ).fetchone()["api_key_ref"]
    assert database.secret_store.get(reference) == raw_secret
