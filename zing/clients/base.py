"""Shared HTTP machinery for relay clients.

Both the OpenAI-compatible and Anthropic-native clients speak raw HTTP (not an
official SDK) so the detectors can reason about the raw evidence — status codes,
headers, partial streams, per-chunk timing. The transport lifecycle, timeout,
secret redaction, and error shaping are identical across protocols and live here;
subclasses only supply the auth headers and the protocol-specific request/response
translation.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx

from zing.models import CompletionOutcome, RequestSpec, TargetConfig
from zing.perf.recorder import RequestRecorder, current_net_trace, net_trace_scope
from zing.utils.redact import redact_json, redact_text

# One TLS context for every relay client in the process. httpx builds a new
# one per AsyncClient (and one more per proxy mount): loading the CA bundle
# costs ~20-30 ms each, on the event loop the audits time their chunks on.
# It is created once, with httpx's own defaults (verification on, CA bundle
# from SSL_CERT_FILE / SSL_CERT_DIR or certifi), off the loop; an
# SSLContext is safe to share between connections and threads. Changing
# those variables later in the process does not affect it.
_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def shared_ssl_context() -> ssl.SSLContext:
    """The process-wide TLS context (created on first use)."""
    global _SSL_CONTEXT
    with _SSL_LOCK:
        if _SSL_CONTEXT is None:
            _SSL_CONTEXT = httpx.create_ssl_context()
        return _SSL_CONTEXT


async def get_ssl_context() -> ssl.SSLContext:
    """The shared TLS context, built in a worker thread the first time (for
    code on the event loop; :func:`shared_ssl_context` blocks)."""
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    return await asyncio.to_thread(shared_ssl_context)


class BaseHTTPClient:
    """Connection lifecycle + redaction + error shaping shared by all clients."""

    def __init__(
        self,
        config: TargetConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.base_url = self._normalize_base_url(config.base_url)
        self._client: httpx.AsyncClient | None = None
        # Set by the runner to log every call for the performance section;
        # ``endpoint`` says which side ("target" / "baseline") this client is.
        self.recorder: RequestRecorder | None = None
        self.endpoint = config.kind

    # -- lifecycle ---------------------------------------------------------- #
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=self._timeout(),
            transport=self.transport,
            verify=await get_ssl_context(),
            headers=self._headers(),
            follow_redirects=False,
            event_hooks={"request": [self._attach_trace]},
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def _session(self):
        """Yield a client: the pooled one if open, else a short-lived one."""
        if self._client is not None:
            yield self._client
            return
        client = httpx.AsyncClient(
            timeout=self._timeout(),
            transport=self.transport,
            verify=await get_ssl_context(),
            headers=self._headers(),
            follow_redirects=False,
            event_hooks={"request": [self._attach_trace]},
        )
        try:
            yield client
        finally:
            await client.aclose()

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        stripped = base_url.strip().rstrip("/")
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return stripped

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.config.timeout_sec,
            connect=min(15.0, self.config.timeout_sec),
        )

    def _extra_secrets(self) -> list[str | None]:
        """Secrets to scrub from any relay-controlled text before it is stored."""
        return [self.config.api_key]

    def _raw_body(self, data: Any, capture: bool) -> dict[str, Any] | None:
        """The redacted raw response body, when the request asked for it."""
        if not capture or not isinstance(data, dict):
            return None
        return redact_json(data, extra_secrets=self._extra_secrets())

    @staticmethod
    async def _attach_trace(request: httpx.Request) -> None:
        """Hand the in-flight call's transport events to its performance trace."""
        net = current_net_trace()
        if net is not None:
            request.extensions["trace"] = net.trace

    # Subclasses provide protocol-specific auth headers and request handling.
    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def _complete(self, spec: RequestSpec) -> CompletionOutcome:
        raise NotImplementedError

    async def _list_models(
        self, headers: dict[str, str] | None = None
    ) -> tuple[CompletionOutcome, list[str]]:
        raise NotImplementedError

    # -- public calls (recorded for the performance section) --------------- #
    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        if self.recorder is None:
            return await self._complete(spec)
        started = time.perf_counter()
        with net_trace_scope() as net:
            outcome = await self._complete(spec)
        self.recorder.record_completion(self.endpoint, spec, outcome, started, net)
        return outcome

    async def list_models(
        self, *, no_cache: bool = False
    ) -> tuple[CompletionOutcome, list[str]]:
        """GET /models. ``no_cache`` asks intermediaries for a fresh answer, for a
        round-trip measurement."""
        headers = {"Cache-Control": "no-cache"} if no_cache else None
        if self.recorder is None:
            return await self._list_models(headers)
        started = time.perf_counter()
        with net_trace_scope() as net:
            outcome, ids = await self._list_models(headers)
        self.recorder.record_models(self.endpoint, outcome, started, net)
        return outcome, ids

    # -- error shaping (shared) -------------------------------------------- #
    def _error_from_response(
        self, response: httpx.Response, duration_ms: float, headers: dict[str, str]
    ) -> CompletionOutcome:
        secrets = self._extra_secrets()
        raw_error: dict[str, Any] | None = None
        message = response.text[:1000]
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                # A relay can echo the bearer token / a sibling key inside the error
                # body, so scrub every string value recursively before we keep it.
                raw_error = redact_json(parsed, extra_secrets=secrets)
                error = parsed.get("error") or parsed
                if isinstance(error, dict):
                    message = str(error.get("message") or error)[:1000]
        except Exception:
            pass
        return CompletionOutcome(
            ok=False,
            status_code=response.status_code,
            duration_ms=duration_ms,
            headers=headers,
            error_type="http_error",
            error_message=redact_text(message, extra_secrets=secrets),
            raw_error=raw_error,
        )

    def _exception_outcome(self, exc: Exception, started: float) -> CompletionOutcome:
        duration_ms = (time.perf_counter() - started) * 1000
        return CompletionOutcome(
            ok=False,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=redact_text(str(exc)[:1000], extra_secrets=self._extra_secrets()),
        )
