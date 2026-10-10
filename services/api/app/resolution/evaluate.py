"""Repeatable, credential-free offline evaluation for resolution paths."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from tests.fakes.llm import ScriptedLLM

from app.resolution.evaluation import evaluate_resolution
from app.resolution.evidence import EvidenceItem, EvidencePacket
from app.resolution.models import GroundedResolutionOutcome
from app.resolution.synthesis import synthesize_resolution
from app.resolution.telemetry import estimated_cost_usd

DEFAULT_CORPUS = Path(__file__).resolve().parents[2] / "tests/fixtures/llm_resolution/cases.json"


def _load(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("evaluation corpus must be a non-empty array")
    for case in value:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise ValueError("each corpus case requires a case_id")
        if not isinstance(case.get("ticket"), dict) or not isinstance(case["ticket"].get("text"), str):
            raise ValueError("each case requires ticket.text")
        expected = case.get("expected")
        evidence = case.get("authorized_evidence")
        if not isinstance(expected, dict) or not isinstance(evidence, list):
            raise ValueError("each case requires expected and authorized_evidence")
        for key in ("abstain", "allowed_action_types"):
            if key not in expected:
                raise ValueError(f"expected.{key} is required")
    return value


def _packet(case: dict[str, Any]) -> EvidencePacket:
    items = []
    for index, item in enumerate(case["authorized_evidence"], 1):
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ("label", "document_id", "source_id", "snippet")):
            raise ValueError("malformed authorized evidence")
        items.append(EvidenceItem(
            label=item["label"], document_id=item["document_id"], source_id=item["source_id"],
            source_type="fixture", title="fixture", snippet=item["snippet"], metadata=(),
            query="fixture", retrieval_mode="lexical", index_version="fixture-v1",
            content_version="fixture-v1", permission_version="fixture-v1",
        ))
    return EvidencePacket(packet_version="offline-v1", items=tuple(items))


def _scripted_payload(case: dict[str, Any], packet: EvidencePacket) -> dict[str, Any]:
    expected = case["expected"]
    abstain = bool(expected["abstain"])
    labels = [item.label for item in packet.items]
    if not labels:
        raise ValueError("scripted resolution requires evidence")
    citation = {"label": labels[0], "source_id": packet.items[0].source_id}
    claim = {"text": "Offline corpus-supported guidance.", "citation_labels": [labels[0]]}
    return {
        "claims": [claim] if not abstain else [], "citations": [citation],
        "steps": [{"instruction": "Review the cited guidance.", "citation_labels": [labels[0]]}] if not abstain else [],
        "customer_response": "Offline evaluation response.", "confidence": expected.get("confidence_band", "low"),
        "abstention": abstain, "next_action": "route_to_human" if abstain else "draft_agent_response",
        "action_proposal": None,
    }


def run_evaluation(corpus_path: str | Path = DEFAULT_CORPUS, *, input_rate: float = 0.0, output_rate: float = 0.0) -> dict[str, Any]:
    """Run deterministic and scripted-model paths and return a redacted summary."""
    cases = _load(Path(corpus_path))
    paths: dict[str, dict[str, Any]] = {}
    for name, scripted in (("deterministic", False), ("scripted_model", True)):
        started = time.perf_counter()
        cited = []
        supported = []
        predicted = []
        expected = []
        actions = []
        allowed = []
        input_tokens = output_tokens = 0
        for case in cases:
            packet = _packet(case)
            exp = case["expected"]
            if scripted:
                if packet.items:
                    client = ScriptedLLM(_scripted_payload(case, packet))
                    before = time.perf_counter()
                    outcome = __import__("asyncio").run(synthesize_resolution(client, case["ticket"]["text"], packet))
                    output_tokens += len(client.calls[0].messages[-1]["content"]) // 4
                    input_tokens += len(case["ticket"]["text"]) // 4
                else:
                    before = time.perf_counter()
                    outcome = GroundedResolutionOutcome(claims=(), citations=(), steps=(), customer_response="No authorized evidence.", confidence="low", abstention=True, next_action="route_to_human", action_proposal=None)
            else:
                before = time.perf_counter()
                outcome = GroundedResolutionOutcome(
                    claims=(), citations=(), steps=(), customer_response="Deterministic path abstained.",
                    confidence="low", abstention=True, next_action="route_to_human", action_proposal=None,
                )
            _ = before
            cited.extend(c.label for c in outcome.citations)
            supported.extend(bool(outcome.citations) for _ in outcome.claims)
            predicted.append(outcome.abstention)
            expected.append(bool(exp["abstain"]))
            actions.append(outcome.next_action)
            allowed.append(exp["allowed_action_types"])
        elapsed = (time.perf_counter() - started) * 1000
        report = evaluate_resolution(cited_labels=cited, authorized_labels=["[E1]", "[E2]"], supported=supported,
            predicted_abstentions=predicted, expected_abstentions=expected, action_types=actions,
            allowed_action_types=allowed, latency_ms=elapsed, input_tokens=input_tokens,
            output_tokens=output_tokens, estimated_cost=estimated_cost_usd(input_tokens=input_tokens, output_tokens=output_tokens, input_rate=input_rate, output_rate=output_rate))
        paths[name] = {"cases": len(cases), "metrics": report.metrics.__dict__, "latency_ms": report.latency_ms,
                       "input_tokens": report.input_tokens, "output_tokens": report.output_tokens, "estimated_cost_usd": report.estimated_cost}
    return {"schema_version": "llm-053-v1", "corpus_cases": len(cases), "paths": paths}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline resolution evaluation")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()
    print(json.dumps(run_evaluation(args.corpus), sort_keys=True))


if __name__ == "__main__":
    main()
