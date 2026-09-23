from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests

PADDLEOCR_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
PADDLEOCR_REMOTE_CLEANUP_STATUS = "unsupported"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_PAGE_BYTES = 20 * 1024 * 1024
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^\)]*\)")
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


class PaddleOcrRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_count = 0
        self.external_request = False
        self.remote_request_id: str | None = None
        self.remote_cleanup_status = "not_applicable"


class PaddleOcrResponseTooLarge(RuntimeError):
    pass


@dataclass(frozen=True)
class PaddleOcrHttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    timeout_seconds: int
    fields: dict[str, str] | None = None
    file_path: Path | None = None


@dataclass(frozen=True)
class PaddleOcrHttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class PaddleOcrResult:
    recognized_text: str
    job_id: str
    retry_count: int
    extracted_pages: int
    remote_cleanup_status: str = PADDLEOCR_REMOTE_CLEANUP_STATUS


Transport = Callable[[PaddleOcrHttpRequest], PaddleOcrHttpResponse]


def requests_transport(request: PaddleOcrHttpRequest) -> PaddleOcrHttpResponse:
    kwargs: dict[str, Any] = {
        "headers": request.headers,
        "timeout": request.timeout_seconds,
        "allow_redirects": False,
        "stream": True,
    }
    source = None
    try:
        if request.file_path is not None:
            source = request.file_path.open("rb")
            kwargs["data"] = request.fields or {}
            kwargs["files"] = {
                "file": (request.file_path.name, source, "image/png"),
            }
        elif request.fields is not None:
            kwargs["data"] = request.fields
        with requests.request(request.method, request.url, **kwargs) as response:
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise PaddleOcrResponseTooLarge
            return PaddleOcrHttpResponse(status=response.status_code, body=bytes(body))
    finally:
        if source is not None:
            source.close()


def validate_public_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PaddleOcrRequestError(
            "OCR_RESULT_URL_REJECTED", "OCR 结果地址不是安全的 HTTPS URL"
        )
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise PaddleOcrRequestError(
            "OCR_RESULT_URL_UNRESOLVED", "OCR 结果地址无法解析"
        ) from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise PaddleOcrRequestError(
            "OCR_RESULT_URL_REJECTED", "OCR 结果地址指向非公网地址，已阻止下载"
        )


class PaddleOcrAiStudioAdapter:
    def __init__(
        self,
        transport: Transport = requests_transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        result_url_validator: Callable[[str], None] = validate_public_https_url,
        poll_interval_seconds: float = 5,
        max_wait_seconds: int = 600,
    ) -> None:
        self.transport = transport
        self.sleep = sleep
        self.monotonic = monotonic
        self.result_url_validator = result_url_validator
        self.poll_interval_seconds = poll_interval_seconds
        self.max_wait_seconds = max_wait_seconds

    def analyze_page(
        self,
        *,
        job_url: str,
        access_token: str,
        default_headers: dict[str, str],
        model_name: str,
        page_path: Path,
        timeout_seconds: int,
        max_retries: int,
        should_continue: Callable[[], bool],
    ) -> PaddleOcrResult:
        if job_url.rstrip("/") != PADDLEOCR_JOB_URL:
            raise PaddleOcrRequestError(
                "OCR_ENDPOINT_REJECTED", "PaddleOCR 仅允许使用已批准的 Jobs Endpoint"
            )
        try:
            page_size = page_path.stat().st_size
        except OSError as exc:
            raise PaddleOcrRequestError(
                "OCR_PAGE_UNREADABLE", "扫描页无法读取，未向 PaddleOCR 发起请求"
            ) from exc
        if page_size > MAX_PAGE_BYTES:
            raise PaddleOcrRequestError(
                "OCR_PAGE_TOO_LARGE", "扫描页超过本地 20 MB 上传安全上限"
            )
        protected_headers = {"accept", "authorization", "content-type", "host", "user-agent"}
        headers = {
            key: value
            for key, value in default_headers.items()
            if key.lower() not in protected_headers
        }
        headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"bearer {access_token}",
                "User-Agent": "Hengjian-Audit-Workbench/0.1",
            }
        )
        fields = {
            "model": model_name,
            "optionalPayload": json.dumps(
                {
                    "useDocOrientationClassify": False,
                    "useDocUnwarping": False,
                    "useChartRecognition": False,
                },
                separators=(",", ":"),
            ),
        }
        retries = 0
        try:
            submitted = self._request(
                PaddleOcrHttpRequest(
                    method="POST",
                    url=PADDLEOCR_JOB_URL,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                    fields=fields,
                    file_path=page_path,
                ),
                max_retries=max_retries,
            )
        except PaddleOcrRequestError as exc:
            exc.external_request = True
            exc.remote_cleanup_status = "unknown"
            raise
        retries += submitted[1]
        try:
            payload = self._json_object(submitted[0].body)
            try:
                job_id = payload["data"]["jobId"]
            except (KeyError, TypeError) as exc:
                raise PaddleOcrRequestError(
                    "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 提交响应缺少 jobId"
                ) from exc
            if not isinstance(job_id, str) or not job_id.strip():
                raise PaddleOcrRequestError(
                    "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 返回了无效 jobId"
                )
        except PaddleOcrRequestError as exc:
            exc.external_request = True
            exc.remote_cleanup_status = "unknown"
            exc.retry_count += retries
            raise
        try:
            started = self.monotonic()
            while True:
                if not should_continue():
                    raise PaddleOcrRequestError(
                        "OCR_TASK_INTERRUPTED", "OCR 任务已在本地安全点中断"
                    )
                if self.monotonic() - started > self.max_wait_seconds:
                    raise PaddleOcrRequestError("OCR_JOB_TIMEOUT", "PaddleOCR 任务等待超时")
                polled = self._request(
                    PaddleOcrHttpRequest(
                        method="GET",
                        url=f"{PADDLEOCR_JOB_URL}/{quote(job_id, safe='')}",
                        headers=headers,
                        timeout_seconds=timeout_seconds,
                    ),
                    max_retries=max_retries,
                )
                retries += polled[1]
                job = self._json_object(polled[0].body)
                try:
                    data = job["data"]
                    state = data["state"]
                except (KeyError, TypeError) as exc:
                    raise PaddleOcrRequestError(
                        "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 状态响应缺少任务状态"
                    ) from exc
                if state in {"pending", "running"}:
                    self.sleep(self.poll_interval_seconds)
                    continue
                if state == "failed":
                    message = data.get("errorMsg") if isinstance(data, dict) else None
                    raise PaddleOcrRequestError(
                        "OCR_JOB_FAILED",
                        str(message).strip() if message else "PaddleOCR 任务处理失败",
                    )
                if state != "done":
                    raise PaddleOcrRequestError(
                        "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 返回了未知任务状态"
                    )
                try:
                    result_url = data["resultUrl"]["jsonUrl"]
                except (KeyError, TypeError) as exc:
                    raise PaddleOcrRequestError(
                        "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 完成响应缺少 JSONL 结果地址"
                    ) from exc
                if not isinstance(result_url, str):
                    raise PaddleOcrRequestError(
                        "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR JSONL 结果地址类型无效"
                    )
                extracted_pages = self._extracted_pages(data)
                break

            self.result_url_validator(result_url)
            downloaded = self._request(
                PaddleOcrHttpRequest(
                    method="GET",
                    url=result_url,
                    headers={"Accept": "application/x-ndjson, application/json"},
                    timeout_seconds=timeout_seconds,
                ),
                max_retries=max_retries,
            )
            retries += downloaded[1]
            recognized_text = self._parse_jsonl(downloaded[0].body)
            return PaddleOcrResult(
                recognized_text=recognized_text,
                job_id=job_id,
                retry_count=retries,
                extracted_pages=extracted_pages,
            )
        except PaddleOcrRequestError as exc:
            exc.external_request = True
            exc.remote_request_id = job_id
            exc.remote_cleanup_status = PADDLEOCR_REMOTE_CLEANUP_STATUS
            exc.retry_count += retries
            raise

    def _request(
        self, request: PaddleOcrHttpRequest, *, max_retries: int
    ) -> tuple[PaddleOcrHttpResponse, int]:
        retries = 0
        while True:
            try:
                response = self.transport(request)
                self._raise_for_status(response.status)
                return response, retries
            except (requests.Timeout, TimeoutError) as exc:
                error = PaddleOcrRequestError("OCR_REQUEST_TIMEOUT", "PaddleOCR 请求超时", retryable=True)
                error.__cause__ = exc
            except requests.ConnectionError as exc:
                error = PaddleOcrRequestError(
                    "OCR_SERVICE_UNAVAILABLE", "PaddleOCR 服务暂时不可用", retryable=True
                )
                error.__cause__ = exc
            except requests.RequestException as exc:
                error = PaddleOcrRequestError(
                    "OCR_REQUEST_FAILED", "PaddleOCR 网络请求失败", retryable=True
                )
                error.__cause__ = exc
            except PaddleOcrResponseTooLarge as exc:
                raise PaddleOcrRequestError(
                    "OCR_RESPONSE_TOO_LARGE", "PaddleOCR 响应超过 16 MB 安全上限"
                ) from exc
            except PaddleOcrRequestError as exc:
                error = exc
            if not error.retryable or retries >= max_retries:
                error.retry_count = retries
                raise error
            retries += 1
            self.sleep(min(2 ** (retries - 1), 4))

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in {301, 302, 303, 307, 308}:
            raise PaddleOcrRequestError("OCR_REDIRECT_REJECTED", "PaddleOCR 返回了未批准的重定向")
        if status in {401, 403}:
            raise PaddleOcrRequestError("OCR_CREDENTIAL_INVALID", "PaddleOCR 拒绝了 Access Token")
        if status == 402:
            raise PaddleOcrRequestError("OCR_BALANCE_INSUFFICIENT", "PaddleOCR 账户余额不足")
        if status == 413:
            raise PaddleOcrRequestError("OCR_PAGE_TOO_LARGE", "扫描页超过 PaddleOCR 上传限制")
        if status == 429:
            raise PaddleOcrRequestError("OCR_RATE_LIMITED", "PaddleOCR 请求过于频繁", retryable=True)
        if status >= 500:
            raise PaddleOcrRequestError(
                "OCR_SERVICE_UNAVAILABLE", "PaddleOCR 服务暂时不可用", retryable=True
            )
        if status >= 400:
            raise PaddleOcrRequestError("OCR_REQUEST_REJECTED", "PaddleOCR 拒绝了页面请求")

    @staticmethod
    def _json_object(body: bytes) -> dict[str, Any]:
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaddleOcrRequestError("OCR_RESPONSE_INVALID_JSON", "PaddleOCR 返回了无效 JSON") from exc
        if not isinstance(value, dict):
            raise PaddleOcrRequestError(
                "OCR_RESPONSE_SCHEMA_INVALID", "PaddleOCR 响应必须是 JSON 对象"
            )
        return value

    @staticmethod
    def _extracted_pages(data: dict[str, Any]) -> int:
        progress = data.get("extractProgress")
        if not isinstance(progress, dict):
            return 1
        value = progress.get("extractedPages", 1)
        return int(value) if isinstance(value, int | float) else 1

    @staticmethod
    def _parse_jsonl(body: bytes) -> str:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PaddleOcrRequestError(
                "OCR_RESULT_ENCODING_INVALID", "PaddleOCR JSONL 结果不是 UTF-8"
            ) from exc
        markdown_pages: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            value = PaddleOcrAiStudioAdapter._json_object(line.encode("utf-8"))
            try:
                layouts = value["result"]["layoutParsingResults"]
            except (KeyError, TypeError) as exc:
                raise PaddleOcrRequestError(
                    "OCR_RESULT_SCHEMA_INVALID", "PaddleOCR JSONL 缺少版面解析结果"
                ) from exc
            if not isinstance(layouts, list):
                raise PaddleOcrRequestError(
                    "OCR_RESULT_SCHEMA_INVALID", "PaddleOCR 版面解析结果类型无效"
                )
            for layout in layouts:
                try:
                    markdown = layout["markdown"]["text"]
                except (KeyError, TypeError) as exc:
                    raise PaddleOcrRequestError(
                        "OCR_RESULT_SCHEMA_INVALID", "PaddleOCR 结果缺少 Markdown 文本"
                    ) from exc
                if not isinstance(markdown, str):
                    raise PaddleOcrRequestError(
                        "OCR_RESULT_SCHEMA_INVALID", "PaddleOCR Markdown 文本类型无效"
                    )
                cleaned = MARKDOWN_IMAGE_PATTERN.sub(r"\1", markdown)
                cleaned = HTML_IMAGE_PATTERN.sub("", cleaned).strip()
                if cleaned:
                    markdown_pages.append(cleaned)
        if not markdown_pages:
            raise PaddleOcrRequestError("OCR_RESULT_EMPTY", "PaddleOCR 未返回可用文本")
        return "\n\n".join(markdown_pages)
