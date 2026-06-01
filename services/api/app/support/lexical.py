# services/api/app/support/lexical.py
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.documents import article_to_document, comment_to_document, ticket_to_document
from app.support.store import support_data_store

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "we",
    "with",
}


@dataclass(frozen=True)
class _LexicalCandidate:
    id: str
    provider: str
    source_type: str
    source_id: str
    title: str
    text: str
    metadata: dict[str, Any]
    tokens: list[str]


async def support_lexical_search(
    session: AsyncSession,
    *,
    tenant_id: str,
    query: str,
    provider: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """BM25-style lexical search over canonical support records.

    This is intentionally dependency-light for local/dev and design-partner
    pilots. Production can swap this behind the same response contract for
    Postgres FTS, OpenSearch, or another full-text engine.
    """
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    candidates = await _candidates(
        session,
        tenant_id=tenant_id,
        provider=provider,
        status=status,
    )
    if not candidates:
        return []

    scored = _bm25_rank(query=query, query_tokens=query_tokens, candidates=candidates)
    return [_to_result(candidate, score) for candidate, score in scored[: max(limit, 1)]]


async def _candidates(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str | None,
    status: str | None,
) -> list[_LexicalCandidate]:
    tickets, _ = await support_data_store.list_tickets(
        session,
        tenant_id=tenant_id,
        provider=provider,
        status=status,
        limit=200,
        offset=0,
    )
    documents = [ticket_to_document(ticket) for ticket in tickets]

    # Status is ticket-only. When status is filtered, keep lexical behavior
    # aligned with vector payload filters by not adding unstatused comments/articles.
    if not status:
        comments, _ = await support_data_store.list_comments(
            session,
            tenant_id=tenant_id,
            provider=provider,
            limit=500,
            offset=0,
        )
        articles, _ = await support_data_store.list_articles(
            session,
            tenant_id=tenant_id,
            provider=provider,
            limit=500,
            offset=0,
        )
        documents.extend(comment_to_document(comment) for comment in comments)
        documents.extend(article_to_document(article) for article in articles)

    candidates: list[_LexicalCandidate] = []
    for doc in documents:
        weighted_text = f"{doc.title} {doc.title} {doc.text}"
        tokens = _tokens(weighted_text)
        if not tokens:
            continue
        candidates.append(
            _LexicalCandidate(
                id=f"lexical:{doc.metadata['tenant_id']}:{doc.provider}:{doc.source_type}:{doc.source_id}",
                provider=doc.provider,
                source_type=doc.source_type,
                source_id=doc.source_id,
                title=doc.title,
                text=doc.text,
                metadata=doc.metadata,
                tokens=tokens,
            )
        )
    return candidates


def _bm25_rank(
    *,
    query: str,
    query_tokens: list[str],
    candidates: list[_LexicalCandidate],
) -> list[tuple[_LexicalCandidate, float]]:
    doc_count = len(candidates)
    avg_len = sum(len(candidate.tokens) for candidate in candidates) / max(doc_count, 1)
    doc_freq = Counter()
    for candidate in candidates:
        doc_freq.update(set(candidate.tokens))

    ranked: list[tuple[_LexicalCandidate, float]] = []
    query_terms = list(dict.fromkeys(query_tokens))
    query_phrase = query.lower().strip()
    for candidate in candidates:
        token_counts = Counter(candidate.tokens)
        score = 0.0
        doc_len = len(candidate.tokens)
        for term in query_terms:
            frequency = token_counts.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (doc_count - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += idf * _bm25_tf(frequency=frequency, doc_len=doc_len, avg_len=avg_len)

        title = candidate.title.lower()
        text = candidate.text.lower()
        if query_phrase and query_phrase in title:
            score *= 1.35
        elif query_phrase and query_phrase in text:
            score *= 1.15

        if score > 0:
            ranked.append((candidate, score))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _bm25_tf(*, frequency: int, doc_len: int, avg_len: float) -> float:
    k1 = 1.5
    b = 0.75
    denominator = frequency + k1 * (1 - b + b * (doc_len / max(avg_len, 1.0)))
    return (frequency * (k1 + 1)) / max(denominator, 0.0001)


def _to_result(candidate: _LexicalCandidate, raw_score: float) -> dict[str, Any]:
    metadata = candidate.metadata
    return {
        "id": candidate.id,
        "score": _normalise(raw_score),
        "lexical_score": raw_score,
        "provider": candidate.provider,
        "source_type": candidate.source_type,
        "source_id": candidate.source_id,
        "title": metadata.get("title") or metadata.get("subject") or candidate.title,
        "text": candidate.text,
        "status": metadata.get("status"),
        "priority": metadata.get("priority"),
        "tags": metadata.get("tags") or [],
        "source_url": metadata.get("source_url"),
        "chunk_index": 0,
        "chunk_count": 1,
        "retrieval_source": "lexical",
    }


def _normalise(score: float) -> float:
    return round(score / (score + 2.0), 4)


def _tokens(value: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{1,}", (value or "").lower()):
        if token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens
