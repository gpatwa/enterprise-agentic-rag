# services/api/app/support/workflow.py
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.insights import repeat_ticket_insights
from app.support.resolver import SupportResolveError, support_resolver


class SupportWorkflowError(RuntimeError):
    pass


async def build_repeat_resolution_workflow(
    session: AsyncSession,
    *,
    tenant_id: str,
    cluster_id: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    limit: int = 200,
    min_count: int = 2,
) -> dict[str, Any]:
    """Build the v1 repeat-cluster workflow used by the /support console.

    The selected cluster is derived from canonical tickets. Resolution evidence
    comes from the support index across all statuses so open-ticket filters do
    not accidentally hide solved cases.
    """
    insights_result = await repeat_ticket_insights(
        session,
        tenant_id=tenant_id,
        provider=provider,
        status=status,
        limit=limit,
        min_count=min_count,
    )
    insights = insights_result["insights"]
    if not insights:
        raise SupportWorkflowError("no repeat issue clusters found")

    insight = _select_insight(insights, cluster_id=cluster_id)
    if insight is None:
        raise SupportWorkflowError("repeat issue cluster not found")

    query = insight["related_query"]
    resolution = await _safe_resolve(
        session=session,
        tenant_id=tenant_id,
        query=query,
        provider=_single_provider(insight) or provider,
    )
    playbook = _playbook(insight, resolution)
    knowledge_gap = _knowledge_gap(insight, resolution)
    deflection_estimate = _deflection_estimate(insight, resolution, knowledge_gap)

    return {
        "cluster": insight,
        "query": query,
        "playbook": playbook,
        "knowledge_gap": knowledge_gap,
        "deflection_estimate": deflection_estimate,
    }


def _select_insight(insights: list[dict[str, Any]], *, cluster_id: str | None) -> dict[str, Any] | None:
    if cluster_id is None:
        return insights[0]
    return next((insight for insight in insights if insight["id"] == cluster_id), None)


async def _safe_resolve(
    *,
    session: AsyncSession,
    tenant_id: str,
    query: str,
    provider: str | None,
) -> dict[str, Any]:
    try:
        return await support_resolver.resolve(
            tenant_id=tenant_id,
            question=query,
            provider=provider,
            status=None,
            limit=6,
            session=session,
        )
    except SupportResolveError as e:
        return {
            "answer": (
                "Resolution evidence is not available yet. Sync/index support data, then rerun "
                "this workflow before using it for agent guidance."
            ),
            "confidence": "low",
            "citations": [],
            "matches": [],
            "next_action": "route_to_human",
            "error": str(e),
        }


def _playbook(insight: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    citations = resolution.get("citations", [])
    matches = resolution.get("matches", [])
    confidence = resolution.get("confidence", "low")
    has_evidence = bool(citations)
    ready_for_review = confidence in {"medium", "high"} and has_evidence
    title = f"{insight['title']} Resolution Playbook"

    return {
        "title": title,
        "status": "ready_for_agent_review" if ready_for_review else "needs_more_evidence",
        "verification_status": "evidence_ready" if ready_for_review else "needs_human_review",
        "issue_signature": insight.get("signals") or insight.get("tags") or [],
        "recommended_resolution": resolution.get("answer", ""),
        "resolution_steps": _resolution_steps(insight, resolution),
        "customer_response_draft": _customer_response_draft(insight, citations),
        "confidence": confidence,
        "evidence_count": len(matches),
        "citations": citations,
        "next_action": resolution.get("next_action", "route_to_human"),
        "guardrails": [
            "Agent must review cited evidence before sending any customer-facing response.",
            "Do not use private/internal comments in customer-facing text until visibility filtering is enforced.",
            "Route to a human if the incoming ticket differs from the issue signature.",
        ],
    }


def _resolution_steps(insight: dict[str, Any], resolution: dict[str, Any]) -> list[str]:
    title = insight["title"].lower()
    steps = [
        f"Confirm the new ticket matches the {title} issue signature.",
        "Review the cited solved tickets or articles before applying the recommendation.",
    ]
    if resolution.get("confidence") == "high":
        steps.append("Apply the proven resolution path and capture any environment-specific exception.")
    elif resolution.get("confidence") == "medium":
        steps.append("Use the recommendation as an agent-assist draft and keep human review in the loop.")
    else:
        steps.append("Collect more solved evidence before turning this into automation.")
    steps.append("Update the macro, help article, or product issue linked to this cluster.")
    return steps


def _customer_response_draft(insight: dict[str, Any], citations: list[dict[str, Any]]) -> str:
    citation_ref = citations[0]["label"] if citations else ""
    citation_suffix = f" {citation_ref}" if citation_ref else ""
    return (
        f"This looks related to a known {insight['title'].lower()} pattern. "
        "We are checking your case against the documented resolution path and will apply the fix "
        f"once an agent verifies the environment details.{citation_suffix}"
    )


def _knowledge_gap(insight: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    matches = resolution.get("matches", [])
    source_types = {match.get("source_type") for match in matches}
    has_article = "article" in source_types
    title = f"How to resolve {insight['title'].lower()} issues"

    if resolution.get("confidence") == "low" or not matches:
        return {
            "status": "needs_more_solved_evidence",
            "severity": "high",
            "article_title": title,
            "recommendation": "Collect at least one confirmed solved case before creating a reusable playbook.",
            "rationale": "The workflow did not find enough cited evidence to safely recommend deflection.",
        }

    if not has_article:
        return {
            "status": "missing_kb_or_macro",
            "severity": "high" if insight.get("count", 0) >= 3 else "medium",
            "article_title": title,
            "recommendation": "Create a help-center article and agent macro from the cited solved-ticket evidence.",
            "rationale": "Repeat tickets exist, but the retrieved evidence does not include a reusable article.",
        }

    if insight.get("potential_deflection_count", 0) > 0:
        return {
            "status": "refresh_existing_kb",
            "severity": "medium",
            "article_title": title,
            "recommendation": "Refresh the existing article or surface it earlier in the support intake flow.",
            "rationale": "Article evidence exists, but customers are still opening repeat tickets.",
        }

    return {
        "status": "monitor",
        "severity": "low",
        "article_title": title,
        "recommendation": "Keep monitoring this issue for recurrence before investing in automation.",
        "rationale": "The current sample does not show a large remaining deflection opportunity.",
    }


def _deflection_estimate(
    insight: dict[str, Any],
    resolution: dict[str, Any],
    knowledge_gap: dict[str, Any],
) -> dict[str, Any]:
    potential = int(insight.get("potential_deflection_count") or 0)
    confidence = _deflection_confidence(insight, resolution, knowledge_gap)
    return {
        "potential_ticket_count": potential,
        "confidence": confidence,
        "estimated_agent_hours_saved": round(potential * 0.25, 2),
        "basis": "Repeat tickets beyond the first observed case in the analyzed sample.",
        "rationale": (
            f"{potential} repeat ticket{'s' if potential != 1 else ''} in this cluster could be reduced "
            "after the playbook is approved and the KB/macro gap is closed."
        ),
        "assumptions": [
            "Average avoidable ticket consumes 15 minutes of agent time.",
            "Only repeat tickets with reusable solved evidence are counted.",
            "Actual deflection must be measured after the KB, macro, or product change ships.",
        ],
    }


def _deflection_confidence(
    insight: dict[str, Any],
    resolution: dict[str, Any],
    knowledge_gap: dict[str, Any],
) -> str:
    if (
        insight.get("deflection_candidate")
        and resolution.get("confidence") == "high"
        and knowledge_gap["status"] != "needs_more_solved_evidence"
    ):
        return "high"
    if insight.get("deflection_candidate") and resolution.get("confidence") in {"medium", "high"}:
        return "medium"
    return "low"


def _single_provider(insight: dict[str, Any]) -> str | None:
    providers = insight.get("providers") or []
    return providers[0] if len(providers) == 1 else None
