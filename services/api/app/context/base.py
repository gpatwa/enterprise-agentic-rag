# services/api/app/context/base.py
"""Protocol for context layer providers."""
from typing import List, Protocol


class ContextLayerProvider(Protocol):
    """Interface that each context layer must implement."""

    async def fetch(
        self,
        query: str,
        tenant_id: str,
        filenames: List[str],
        user_role: str = "all",
    ) -> str:
        """
        Return a formatted context string for this layer.

        Args:
            query: The user's query text.
            tenant_id: Tenant scope for data isolation.
            filenames: Filenames from retrieved documents (for Layer 1 metadata lookups).
            user_role: Current user's role (for Layer 4 role-based filtering).

        Returns:
            Formatted context string, or empty string if no relevant context found.
        """
        ...
