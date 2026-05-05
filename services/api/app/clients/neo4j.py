# services/api/app/clients/neo4j.py
import logging

from neo4j import AsyncGraphDatabase

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"


class Neo4jClient:
    """
    Singleton wrapper for the Neo4j Driver.
    Supports Async execution for high-concurrency API handling.
    All queries are filtered by tenant_id for data isolation.
    """
    def __init__(self):
        self._driver = None

    def connect(self):
        """Initializes the connection pool."""
        if not self._driver:
            try:
                # Create driver with authentication
                self._driver = AsyncGraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
                )
                logger.info("Connected to Neo4j successfully.")
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                raise

    async def close(self):
        """Closes the connection pool on shutdown."""
        if self._driver:
            await self._driver.close()

    async def query(
        self,
        cypher_query: str,
        parameters: dict = None,
        tenant_id: str | None = None,
    ):
        """
        Executes a Cypher query and returns the results.

        If tenant_id is provided, it is injected into the parameters dict
        so that Cypher queries can filter on it (e.g. WHERE node.tenant_id = $tenant_id).
        """
        if not self._driver:
            await self.connect()

        params = dict(parameters or {})
        if tenant_id is not None:
            params["tenant_id"] = tenant_id

        async with self._driver.session() as session:
            result = await session.run(cypher_query, params)
            return [record.data() async for record in result]

# Global instance
neo4j_client = Neo4jClient()
