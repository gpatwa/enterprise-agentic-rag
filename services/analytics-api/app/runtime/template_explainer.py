"""A deterministic explainer for the pilot: grounded sentences from the result's first row, no second model call.

Every number it writes is a cell of the result and is cited, so the explanation grounding check always passes or degrades to
evidence-only; it costs nothing per answer. A model-written explainer can replace it later.
"""

from __future__ import annotations


def template_explainer(sheet, violations):
    from app.execution import DraftClaim

    first, second = sheet.get("cell:r0c0"), sheet.get("cell:r0c1")
    if first is None:
        raise LookupError("no rows to explain")
    metric = next((fact.fact_id for fact in sheet.facts if fact.fact_id.startswith("metric:")), None)
    cites = ("cell:r0c0",) + (("cell:r0c1",) if second is not None else ()) + ((metric,) if metric else ())
    if second is None:
        return [DraftClaim(f"The total is {first.value}.", cites)]
    return [DraftClaim(f"The top result is {first.value} with {second.value}.", cites)]
