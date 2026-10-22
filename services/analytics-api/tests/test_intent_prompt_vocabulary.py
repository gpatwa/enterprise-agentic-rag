"""A real model only knows what the prompt shows it: it must see the certified ids and the identity it has to echo."""

import json

from app.config import Settings
from app.context.registry_context import SnapshotSearch, certified_vocabulary, context_from_contract
from app.runtime.context_node import build_context_pack
from app.runtime.intent_node import _prompt
from app.runtime.pilot_wiring import _contract_documents


def _document():
    return _contract_documents(Settings().ANALYTICS_SEMANTIC_REGISTRY_PATH, ["sales-core@v1"])[0]


def test_vocabulary_lists_certified_ids_only():
    vocabulary = json.loads(certified_vocabulary(_document()))
    assert vocabulary["semantic_contract"] == {"contract_id": "sales-core", "contract_version": "v1"}
    assert {m["metric_id"] for m in vocabulary["metrics"]} == {"revenue"}
    assert "status" in {d["dimension_id"] for d in vocabulary["dimensions"]}
    assert "owner" not in json.dumps(vocabulary)


def test_default_prompt_carries_identity_and_vocabulary():
    document = _document()
    context, _ = context_from_contract(document)
    question = "What was total revenue by status?"
    found = SnapshotSearch(context).search(question, tenant_id=context.tenant_id, snapshot_id=context.snapshot_id)
    pack = build_context_pack(
        context, tuple(found), query=question, token_budget=4000, graph_depth=1, max_graph_edges=24
    )
    prompt = _prompt(question, pack, "run-1:key", certified_vocabulary(document))
    assert 'Set query_id to "run-1:key"' in prompt
    assert '"metric_id":"revenue"' in prompt
