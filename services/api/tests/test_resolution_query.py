from __future__ import annotations

import pytest


def test_normalizes_whitespace_and_control_characters_without_changing_exact_terms():
    from app.resolution.query import normalize_ticket_query

    result = normalize_ticket_query('  ERR-104\tfrom\n"keep  this"\r v2.4.1  ')

    assert result.query == 'ERR-104 from "keep this" v2.4.1'
    assert result.obvious_route == "exact_error"
    assert result.llm_required is False


@pytest.mark.parametrize(
    ("ticket", "route"),
    [
        ("HTTP 503 from the export API", "exact_error"),
        ("I cannot access the admin console", "access"),
        ("The invoice shows an unexpected charge", "billing"),
        ("How do I configure SSO?", "how_to"),
        ("Upgrade from version 2.3.0", "version"),
    ],
)
def test_obvious_routes_do_not_require_an_llm(ticket, route):
    from app.resolution.query import normalize_ticket_query

    result = normalize_ticket_query(ticket)

    assert result.obvious_route == route
    assert result.llm_required is False


@pytest.mark.parametrize("ticket", ["ERR_EXPORT_504 after retry", "release v3 requires setup"])
def test_preserves_symbolic_error_codes_and_short_versions(ticket):
    from app.resolution.query import normalize_ticket_query

    result = normalize_ticket_query(ticket)

    assert ticket in result.query
    assert result.llm_required is False


def test_ambiguous_ticket_requires_llm():
    from app.resolution.query import normalize_ticket_query

    result = normalize_ticket_query("Exports fail intermittently after a deploy")

    assert result.obvious_route is None
    assert result.llm_required is True


@pytest.mark.parametrize("ticket", ["", " \t\n", "x" * 4001, None])
def test_rejects_blank_oversized_and_non_string_input(ticket):
    from app.resolution.query import normalize_ticket_query

    with pytest.raises(ValueError):
        normalize_ticket_query(ticket)
