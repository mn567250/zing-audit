"""Context-window detector tests — truncation vs. parameter-rejection.

A real context-length rejection is a truncation signal; a max_tokens parameter
rejection (reasoning models) must NOT be misread as a shrunken context window.
"""

from __future__ import annotations

from zing.detectors.context_window import ContextWindowDetector
from zing.models import CompletionOutcome, Status


def _outcome(status_code, message, *, needle="ZING-ABC", content="", ok=False):
    return CompletionOutcome(
        ok=ok,
        status_code=status_code,
        content=content,
        error_message=message,
        headers={"x-zing-needle": needle},
    )


def test_classify_context_length_error_is_size_rejection():
    o = _outcome(400, "This model's maximum context length is 8192 tokens; reduce the length of the messages")
    recalled, rejected, status = ContextWindowDetector._classify(o, 16000)
    assert recalled is False and rejected is True and status == "rejected"


def test_classify_max_tokens_param_error_is_not_size_rejection():
    o = _outcome(400, "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens'.")
    recalled, rejected, status = ContextWindowDetector._classify(o, 16000)
    assert rejected is False and status == "param_error"


def test_classify_recall_hit():
    o = _outcome(200, None, needle="ZING-ABC", content="the secret pass phrase is ZING-ABC", ok=True)
    recalled, rejected, status = ContextWindowDetector._classify(o, 4000)
    assert recalled is True and status == "recalled"


async def test_truncation_below_claim_is_flagged(audit_context, mock_server):
    # gpt-4o claims a 128K window, but the relay rejects anything past ~6000 chars.
    mock_server.truncate_above_tokens = 6000
    result = await ContextWindowDetector().run(audit_context)
    assert result.status == Status.FAIL
    assert any(
        f.id in ("context_window.truncation", "context_window.no_recall",
                 "context_window.rejected_below_claim")
        for f in result.findings
    )


def test_classify_timeout_is_its_own_status():
    o = CompletionOutcome(ok=False, error_type="ReadTimeout", headers={"x-zing-needle": "N"})
    assert ContextWindowDetector._classify(o, 16000) == (False, False, "timeout")


async def test_timeout_is_inconclusive_not_truncation(audit_context):
    # A slow endpoint: recalls small prompts, times out on large ones.
    real = audit_context.client.complete
    timed_out_sizes: list[int] = []

    async def slow_complete(spec):
        size = len(spec.messages[0]["content"])
        if size > 20_000:
            timed_out_sizes.append(size)
            return CompletionOutcome(ok=False, error_type="ReadTimeout", error_message="timed out")
        return await real(spec)

    audit_context.client.complete = slow_complete
    result = await ContextWindowDetector().run(audit_context)
    ids = {f.id for f in result.findings}
    assert result.status == Status.INCONCLUSIVE
    assert result.score is None
    assert "context_window.timed_out" in ids
    assert not ids & {"context_window.truncation", "context_window.short", "context_window.no_recall"}
    # The ladder stops at the first timeout instead of retrying the other edge.
    assert len(timed_out_sizes) == 1
