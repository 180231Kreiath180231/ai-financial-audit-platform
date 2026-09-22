from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class CompletionResult:
    content: str
    input_tokens: int
    output_tokens: int
    retry_count: int


class ProviderRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_count = 0


Transport = Callable[[str, bytes, dict[str, str], int], HttpResponse]


def urllib_transport(
    url: str, payload: bytes, headers: dict[str, str], timeout_seconds: int
) -> HttpResponse:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(status=response.status, body=response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, body=exc.read())


class OpenAICompatibleAdapter:
    def __init__(
        self,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.sleep = sleep

    def complete(
        self,
        *,
        base_url: str,
        api_key: str,
        default_headers: dict[str, str],
        model_name: str,
        prompt: str,
        timeout_seconds: int,
        max_retries: int,
    ) -> CompletionResult:
        url = f"{base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Hengjian-Audit-Workbench/0.1",
            **default_headers,
        }
        retries = 0
        while True:
            try:
                response = self.transport(url, body, headers, timeout_seconds)
                result = self._parse_response(response, retries)
                return result
            except (TimeoutError, urllib.error.URLError) as exc:
                error = ProviderRequestError(
                    "MODEL_TIMEOUT" if isinstance(exc, TimeoutError) else "MODEL_SERVICE_UNAVAILABLE",
                    "模型请求超时" if isinstance(exc, TimeoutError) else "模型服务暂时不可用",
                    retryable=True,
                )
            except ProviderRequestError as exc:
                error = exc
            if not error.retryable or retries >= max_retries:
                error.retry_count = retries
                raise error
            retries += 1
            self.sleep(min(2 ** (retries - 1), 4))

    @staticmethod
    def _parse_response(response: HttpResponse, retries: int) -> CompletionResult:
        if response.status in {401, 403}:
            raise ProviderRequestError("MODEL_CREDENTIAL_INVALID", "模型服务拒绝了 API Key")
        if response.status == 402:
            raise ProviderRequestError("MODEL_BALANCE_INSUFFICIENT", "模型服务余额不足")
        if response.status == 429:
            raise ProviderRequestError("MODEL_RATE_LIMITED", "模型服务请求过于频繁", retryable=True)
        if response.status >= 500:
            raise ProviderRequestError(
                "MODEL_SERVICE_UNAVAILABLE", "模型服务暂时不可用", retryable=True
            )
        if response.status >= 400:
            raise ProviderRequestError("MODEL_REQUEST_REJECTED", "模型服务拒绝了请求")
        try:
            payload: dict[str, Any] = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderRequestError("MODEL_RESPONSE_INVALID_JSON", "模型返回了无效 JSON") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderRequestError("MODEL_RESPONSE_SCHEMA_INVALID", "模型响应缺少必要字段") from exc
        if not isinstance(content, str):
            raise ProviderRequestError("MODEL_RESPONSE_SCHEMA_INVALID", "模型响应内容类型无效")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return CompletionResult(
            content=content,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            retry_count=retries,
        )
