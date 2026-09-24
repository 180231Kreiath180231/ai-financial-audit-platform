from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from .db import Database, utc_now
from .gateway import GatewayError, ModelGateway

SCAN_TEXT_MIN_CHARACTERS = 12
VISION_SCHEMA_VERSION = "vision-page.v1"
NATIVE_PARSE_VERSION = "pypdf-v2"
FAKE_VISION_PARSE_VERSION = "fake-vision-v1"
SCAN_DETECT_PARSE_VERSION = "scan-detect-v1"
PADDLEOCR_PARSE_VERSION = "paddleocr-aistudio-v1"


def is_scanned_page(text: str) -> bool:
    meaningful = sum(1 for character in text if not character.isspace())
    return meaningful < SCAN_TEXT_MIN_CHARACTERS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ScanVisionService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.gateway = ModelGateway(database)

    def analyze_pages(
        self,
        *,
        project_id: str,
        root: Path,
        task_id: str,
        source: Path,
        filename: str,
        page_text: list[str],
        safe_point: Callable[[Path, str, Path], bool],
    ) -> list[dict[str, Any]] | None:
        project = self.database.get_project(project_id)
        synthetic = bool(project["is_synthetic"])
        use_paddleocr = False
        if (
            synthetic
            and project["external_access_enabled"]
            and not self.database.strict_offline()
        ):
            try:
                self.gateway.route(
                    project_id,
                    "vision",
                    provider_kind="paddleocr_aistudio",
                )
                use_paddleocr = True
            except GatewayError as exc:
                if exc.code != "MODEL_ROUTE_UNAVAILABLE":
                    raise
        analyses: list[dict[str, Any]] = []
        for index, text in enumerate(page_text):
            page_number = index + 1
            if not is_scanned_page(text):
                analyses.append(self._native_result(page_number, text))
                continue
            if not safe_point(root, task_id, source):
                return None
            checkpoint = self._load_external_checkpoint(root, task_id, page_number)
            if checkpoint is not None:
                analyses.append(checkpoint)
                self.database.record_project_event(
                    root,
                    "task.external_vision_checkpoint_reused",
                    task_id=task_id,
                    details={
                        "page_number": page_number,
                        "model_call_id": checkpoint["model_call_id"],
                    },
                )
                if not safe_point(root, task_id, source):
                    return None
                continue
            if not synthetic:
                analyses.append(self._pending_result(page_number))
                continue
            result = (
                self._paddleocr_result(
                    project_id=project_id,
                    root=root,
                    task_id=task_id,
                    source=source,
                    filename=filename,
                    page_number=page_number,
                    safe_point=safe_point,
                )
                if use_paddleocr
                else self._fake_result(
                    project_id=project_id,
                    root=root,
                    task_id=task_id,
                    source=source,
                    filename=filename,
                    page_number=page_number,
                )
            )
            if result is None:
                return None
            if result["status"] == "completed" and result["external_request"]:
                self._save_external_checkpoint(root, task_id, result)
            analyses.append(result)
            if not safe_point(root, task_id, source):
                return None
        return analyses

    def _load_external_checkpoint(
        self, root: Path, task_id: str, page_number: int
    ) -> dict[str, Any] | None:
        with self.database.connect(root / "app.db") as db:
            row = db.execute(
                """SELECT analysis_json FROM task_page_checkpoints
                WHERE task_id=? AND page_number=? AND checkpoint_kind='external_vision'""",
                (task_id, page_number),
            ).fetchone()
        if row is None:
            return None
        analysis = json.loads(row["analysis_json"])
        if (
            analysis.get("status") != "completed"
            or not analysis.get("external_request")
            or analysis.get("parse_version") != PADDLEOCR_PARSE_VERSION
        ):
            return None
        return analysis

    def _save_external_checkpoint(
        self, root: Path, task_id: str, analysis: dict[str, Any]
    ) -> None:
        now = utc_now()
        serialized = json.dumps(
            analysis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.database.connect(root / "app.db") as db:
            db.execute(
                """INSERT INTO task_page_checkpoints
                (task_id, page_number, checkpoint_kind, analysis_json, created_at, updated_at)
                VALUES (?, ?, 'external_vision', ?, ?, ?)
                ON CONFLICT(task_id, page_number, checkpoint_kind) DO UPDATE SET
                    analysis_json=excluded.analysis_json,
                    updated_at=excluded.updated_at""",
                (task_id, analysis["page_number"], serialized, now, now),
            )
        self.database.record_project_event(
            root,
            "task.external_vision_checkpoint_saved",
            task_id=task_id,
            details={
                "page_number": analysis["page_number"],
                "model_call_id": analysis["model_call_id"],
                "remote_request_id": analysis["remote_request_id"],
            },
        )

    @staticmethod
    def _native_result(page_number: int, text: str) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "page_number": page_number,
            "status": "not_required",
            "provider_id": None,
            "model_profile_id": None,
            "provider_name": None,
            "actual_model": None,
            "model_call_id": None,
            "schema_version": VISION_SCHEMA_VERSION,
            "recognized_text": text,
            "confidence": None,
            "result_json": "{}",
            "image_sha256": None,
            "external_request": False,
            "remote_request_id": None,
            "remote_cleanup_status": "not_applicable",
            "error_code": None,
            "error_message": None,
            "parse_method": "native_pdf",
            "parse_version": NATIVE_PARSE_VERSION,
        }

    @staticmethod
    def _pending_result(page_number: int) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "page_number": page_number,
            "status": "requires_vision",
            "provider_id": None,
            "model_profile_id": None,
            "provider_name": None,
            "actual_model": None,
            "model_call_id": None,
            "schema_version": VISION_SCHEMA_VERSION,
            "recognized_text": "",
            "confidence": None,
            "result_json": "{}",
            "image_sha256": None,
            "external_request": False,
            "remote_request_id": None,
            "remote_cleanup_status": "not_applicable",
            "error_code": None,
            "error_message": None,
            "parse_method": "scan_detected",
            "parse_version": SCAN_DETECT_PARSE_VERSION,
        }

    def _fake_result(
        self,
        *,
        project_id: str,
        root: Path,
        task_id: str,
        source: Path,
        filename: str,
        page_number: int,
    ) -> dict[str, Any]:
        temp_path = root / "temp" / f"{task_id}-page-{page_number}.png"
        pdf_document = pdfium.PdfDocument(str(source))
        page = pdf_document[page_number - 1]
        bitmap = None
        image = None
        try:
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            image.save(temp_path, format="PNG", optimize=True)
            width, height = image.size
            image_sha256 = _sha256(temp_path)
            response = self.gateway.analyze_fake_vision_page(
                project_id,
                task_id=task_id,
                document_name=filename,
                page_number=page_number,
                image_sha256=image_sha256,
                width=width,
                height=height,
            )
            result = response["result"]
            return {
                "id": str(uuid.uuid4()),
                "page_number": page_number,
                "status": "completed",
                "provider_id": response["provider_id"],
                "model_profile_id": response["model_profile_id"],
                "provider_name": response["provider"],
                "actual_model": response["actual_model"],
                "model_call_id": response["call_id"],
                "schema_version": result["schema_version"],
                "recognized_text": result["recognized_text"],
                "confidence": result["confidence"],
                "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
                "image_sha256": image_sha256,
                "external_request": False,
                "remote_request_id": None,
                "remote_cleanup_status": "not_applicable",
                "error_code": None,
                "error_message": None,
                "parse_method": "fake_vision",
                "parse_version": FAKE_VISION_PARSE_VERSION,
            }
        finally:
            if image is not None:
                image.close()
            if bitmap is not None:
                bitmap.close()
            page.close()
            pdf_document.close()
            temp_path.unlink(missing_ok=True)

    def _paddleocr_result(
        self,
        *,
        project_id: str,
        root: Path,
        task_id: str,
        source: Path,
        filename: str,
        page_number: int,
        safe_point: Callable[[Path, str, Path], bool],
    ) -> dict[str, Any] | None:
        temp_path = root / "temp" / f"{task_id}-page-{page_number}.png"
        pdf_document = pdfium.PdfDocument(str(source))
        page = pdf_document[page_number - 1]
        bitmap = None
        image = None
        image_sha256 = None
        try:
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            image.save(temp_path, format="PNG", optimize=True)
            width, height = image.size
            image_sha256 = _sha256(temp_path)
            try:
                response = self.gateway.analyze_paddleocr_page(
                    project_id,
                    task_id=task_id,
                    document_name=filename,
                    page_number=page_number,
                    image_path=temp_path,
                    image_sha256=image_sha256,
                    width=width,
                    height=height,
                    should_continue=lambda: safe_point(root, task_id, source),
                )
            except GatewayError as exc:
                if exc.code == "OCR_TASK_INTERRUPTED":
                    return None
                return {
                    "id": str(uuid.uuid4()),
                    "page_number": page_number,
                    "status": "failed",
                    "provider_id": None,
                    "model_profile_id": None,
                    "provider_name": "PaddleOCR AI Studio",
                    "actual_model": "PaddleOCR-VL-1.6",
                    "model_call_id": exc.call_id,
                    "schema_version": VISION_SCHEMA_VERSION,
                    "recognized_text": "",
                    "confidence": None,
                    "result_json": "{}",
                    "image_sha256": image_sha256,
                    "external_request": exc.external_request,
                    "remote_request_id": exc.remote_request_id,
                    "remote_cleanup_status": exc.remote_cleanup_status,
                    "error_code": exc.code,
                    "error_message": f"{exc.message}；{exc.action}",
                    "parse_method": "paddleocr_failed",
                    "parse_version": PADDLEOCR_PARSE_VERSION,
                }
            result = response["result"]
            return {
                "id": str(uuid.uuid4()),
                "page_number": page_number,
                "status": "completed",
                "provider_id": response["provider_id"],
                "model_profile_id": response["model_profile_id"],
                "provider_name": response["provider"],
                "actual_model": response["actual_model"],
                "model_call_id": response["call_id"],
                "schema_version": result["schema_version"],
                "recognized_text": result["recognized_text"],
                "confidence": result["confidence"],
                "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
                "image_sha256": image_sha256,
                "external_request": True,
                "remote_request_id": response["remote_request_id"],
                "remote_cleanup_status": response["remote_cleanup_status"],
                "error_code": None,
                "error_message": None,
                "parse_method": "paddleocr_vision",
                "parse_version": PADDLEOCR_PARSE_VERSION,
            }
        finally:
            if image is not None:
                image.close()
            if bitmap is not None:
                bitmap.close()
            page.close()
            pdf_document.close()
            temp_path.unlink(missing_ok=True)


def vision_row_values(document_id: str, analysis: dict[str, Any]) -> tuple[Any, ...]:
    now = utc_now()
    return (
        analysis["id"],
        document_id,
        analysis["page_number"],
        analysis["status"],
        analysis["provider_id"],
        analysis["model_profile_id"],
        analysis["provider_name"],
        analysis["actual_model"],
        analysis["model_call_id"],
        analysis["schema_version"],
        analysis["recognized_text"],
        analysis["confidence"],
        analysis["result_json"],
        analysis["image_sha256"],
        int(analysis["external_request"]),
        analysis["error_code"],
        analysis["error_message"],
        analysis["remote_request_id"],
        analysis["remote_cleanup_status"],
        now,
        now,
    )
