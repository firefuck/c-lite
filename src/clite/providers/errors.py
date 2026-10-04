"""API error classification: one place decides what a failure means and what to try next.

The retry loop never inspects status codes or message strings itself. It asks
:func:`classify_api_error` and follows the hints on the result.
"""

from __future__ import annotations

import http.client
import socket
from dataclasses import dataclass
from enum import Enum

from clite.providers.http import Cancelled, ProviderHTTPError


class FailoverReason(str, Enum):
    AUTH = "auth"
    BILLING = "billing"
    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    MODEL_NOT_FOUND = "model_not_found"
    FORMAT_ERROR = "format_error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedError:
    reason: FailoverReason
    message: str
    status_code: int | None = None
    retryable: bool = False  # the same request may succeed if sent again
    should_compress: bool = False  # shrink the context, then retry
    should_rotate_credential: bool = False  # try another key for the same provider
    should_fallback: bool = False  # move to the next provider in the fallback chain
    retry_after: float | None = None

    def user_message(self) -> str:
        prefix = f"[{self.status_code}] " if self.status_code else ""
        return f"{prefix}{self.reason.value}: {self.message}"


_CONTEXT_PHRASES = (
    "context length", "context_length", "maximum context", "context window", "too many tokens",
    "prompt is too long", "reduce the length", "exceeds the model", "input is too long", "token limit",
    "max_tokens_exceeded", "maximum number of tokens",
)
_BILLING_PHRASES = ("insufficient credit", "insufficient_quota", "billing", "payment required", "out of credits",
                    "credit balance", "quota exceeded", "exceeded your current quota")
_MODEL_PHRASES = ("model not found", "model_not_found", "does not exist", "no such model", "unknown model",
                  "is not a valid model", "not_found_error")
_OVERLOAD_PHRASES = ("overloaded", "over capacity", "temporarily unavailable")


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _retry_after(error: ProviderHTTPError) -> float | None:
    for header in ("retry-after-ms", "retry-after"):
        raw = error.headers.get(header)
        if raw:
            try:
                value = float(raw)
            except ValueError:
                continue
            return value / 1000 if header.endswith("-ms") else value
    return None


def classify_api_error(exc: BaseException) -> ClassifiedError:
    if isinstance(exc, (Cancelled, InterruptedError)):
        return ClassifiedError(FailoverReason.CANCELLED, "cancelled")
    if isinstance(exc, ProviderHTTPError):
        return _classify_http(exc)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ClassifiedError(FailoverReason.TIMEOUT, f"timed out: {exc}", retryable=True, should_fallback=True)
    if isinstance(exc, (ConnectionError, http.client.HTTPException, OSError)):
        return ClassifiedError(FailoverReason.TIMEOUT, f"connection failed: {exc}", retryable=True, should_fallback=True)
    return ClassifiedError(FailoverReason.UNKNOWN, f"{type(exc).__name__}: {exc}")


def _classify_http(error: ProviderHTTPError) -> ClassifiedError:
    status = error.status
    text = f"{error.message} {error.error_type}".lower()
    message = error.message or f"HTTP {status}"
    retry_after = _retry_after(error)

    def result(reason: FailoverReason, **hints: bool) -> ClassifiedError:
        return ClassifiedError(reason, message, status, retry_after=retry_after, **hints)

    # Message checks first: providers disagree on which status carries which problem.
    if _has(text, _CONTEXT_PHRASES) and status in (400, 413, 422, 429):
        return result(FailoverReason.CONTEXT_OVERFLOW, should_compress=True)
    if status == 413:
        return result(FailoverReason.PAYLOAD_TOO_LARGE, should_compress=True)
    if status == 402 or _has(text, _BILLING_PHRASES):
        return result(FailoverReason.BILLING, should_rotate_credential=True, should_fallback=True)
    if status in (401, 403):
        return result(FailoverReason.AUTH, should_rotate_credential=True, should_fallback=True)
    if status == 404 or (status == 400 and _has(text, _MODEL_PHRASES)):
        return result(FailoverReason.MODEL_NOT_FOUND, should_fallback=True)
    if status == 429:
        return result(FailoverReason.RATE_LIMIT, retryable=True, should_rotate_credential=True, should_fallback=True)
    if status == 529 or _has(text, _OVERLOAD_PHRASES):
        return result(FailoverReason.OVERLOADED, retryable=True, should_fallback=True)
    if status >= 500:
        return result(FailoverReason.SERVER_ERROR, retryable=True, should_fallback=True)
    if status in (400, 422):
        return result(FailoverReason.FORMAT_ERROR)
    return result(FailoverReason.UNKNOWN)
