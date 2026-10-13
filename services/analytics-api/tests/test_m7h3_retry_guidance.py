"""M7-H3: a failed run tells the caller how to retry; the same idempotency key returns the same failure."""

from __future__ import annotations

from unittest import mock

from reference_stack import stack as stack_module
from reference_stack.stack import build_stack

PURPOSE = "analytics"


def _down(*args, **kwargs):
    class Client:
        def complete_json(self, **_):
            raise ConnectionError("down")

    return Client()


def test_a_retryable_failure_says_to_resubmit_with_a_new_key_and_the_same_key_returns_the_same_failure(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    with mock.patch.object(stack_module, "ScriptedIntentClient", _down):
        first = stack.service().analyze(
            who, purpose=PURPOSE, idempotency_key="retry-key-000001", request_text="Show monthly revenue"
        )
    assert (
        first.outcome.outcome == "failed"
        and first.outcome.retryable
        and first.outcome.retry_guidance == "resubmit_with_new_idempotency_key"
    )
    same = stack.service().analyze(
        who, purpose=PURPOSE, idempotency_key="retry-key-000001", request_text="Show monthly revenue"
    )
    assert same.run_id == first.run_id and same.outcome.outcome == "failed"  # a retry under the same key is not a retry
    fresh = stack.service().analyze(
        who, purpose=PURPOSE, idempotency_key="retry-key-000002", request_text="Show monthly revenue"
    )
    assert fresh.run_id != first.run_id and fresh.outcome.outcome == "answer"


def test_a_failure_that_a_retry_cannot_fix_carries_no_guidance(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    from app.runtime.analyze_service import _failure

    assert _failure(["something_unexpected"], "failed") == ("internal_error", "The run failed.", False)
    from packages.platform_contracts.analytics_v2 import AnalyticsFailedOutcome

    outcome = AnalyticsFailedOutcome(
        contract_version="v2",
        query_id="q",
        tenant_id="t",
        user_id="u",
        dataset="d",
        generated_at="2026-10-13T00:00:00Z",
        error_code="internal_error",
        message="The run failed.",
        retryable=False,
    )
    assert outcome.retry_guidance is None and who is not None


def test_a_missing_answer_after_a_restart_tells_the_caller_to_ask_again(tmp_path):
    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    run = stack.service().analyze(
        who, purpose=PURPOSE, idempotency_key="retry-key-000003", request_text="Show monthly revenue"
    )
    restarted = build_stack("duckdb", tmp_path)
    reply = restarted.service().status(who, purpose=PURPOSE, run_id=run.run_id)
    assert reply.outcome.outcome == "failed" and reply.outcome.retry_guidance == "resubmit_with_new_idempotency_key"
