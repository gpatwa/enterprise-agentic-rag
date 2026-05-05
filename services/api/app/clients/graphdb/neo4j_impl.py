# services/api/app/clients/graphdb/neo4j_impl.py
"""
Neo4j implementation of the GraphDBClient protocol.
Wraps the AsyncGraphDatabase driver with a provider-agnostic interface.
"""
import logging

from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)


class Neo4jGraphClient:
    """
    Neo4j-backed GraphDBClient.

    Uses full-text index search for query_related() and
    Cypher MERGE for upsert_triples().
    """

    def __init__(self, uri: str, user: str, password: str):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver = None

    async def connect(self) -> None:
        if not self._driver:
            try:
                self._driver = AsyncGraphDatabase.driver(
                    self._uri,
                    auth=(self._user, self._password),
                )
                logger.info("Neo4jGraphClient connected successfully.")
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                raise

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None

    @property
    def is_connected(self) -> bool:
        return self._driver is not None

    async def query_related(
        self,
        query: str,
        tenant_id: str,
        limit: int = 5,
    ) -> list[str]:
        """
        Search the graph using the full-text 'entity_index'.
        Results are filtered by tenant_id on both the source node
        and its neighbours.
        """
        if not self._driver:
            await self.connect()

        cypher = """
        CALL db.index.fulltext.queryNodes("entity_index", $query)
        YIELD node, score
        WHERE node.tenant_id = $tenant_id OR node.tenant_id IS NULL
        MATCH (node)-[r]->(neighbor)
        WHERE neighbor.tenant_id = $tenant_id OR neighbor.tenant_id IS NULL
        RETURN node.name + ' ' + type(r) + ' ' + neighbor.name AS text
        LIMIT $limit
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    cypher,
                    {"query": query, "tenant_id": tenant_id, "limit": limit},
                )
                records = [record.data() async for record in result]
                return [r["text"] for r in records]
        except Exception as e:
            logger.error(f"Graph query_related failed: {e}")
            return []

    async def upsert_triples(
        self,
        triples: list[dict],
        tenant_id: str,
    ) -> None:
        """
        Merge entity triples into Neo4j.
        Each triple: {"source": str, "target": str, "type": str}
        """
        if not self._driver:
            await self.connect()

        cypher = """
        UNWIND $triples AS t
        MERGE (s:Entity {name: t.source, tenant_id: $tenant_id})
        MERGE (tgt:Entity {name: t.target, tenant_id: $tenant_id})
        MERGE (s)-[r:RELATED {type: t.type}]->(tgt)
        """
        async with self._driver.session() as session:
            await session.run(
                cypher,
                {"triples": triples, "tenant_id": tenant_id},
            )
