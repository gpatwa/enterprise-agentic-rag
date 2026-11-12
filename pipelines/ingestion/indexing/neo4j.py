# pipelines/ingestion/indexing/neo4j.py
import os
from typing import Any, Dict, List

from neo4j import GraphDatabase

DEFAULT_TENANT_ID = "default"


class Neo4jIndexer:
    """
    Writes data to Neo4j Graph Database.
    Implements efficient Batch Writes.
    All nodes and edges are tagged with tenant_id for isolation.
    """
    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
        # Read from Env Vars (injected by Ray Cluster environment)
        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "changeme")
        self.tenant_id = tenant_id
        self._uri = uri
        self._auth = (user, password)
        # The driver holds locks and sockets, so it is created on first use in the process that writes and is
        # never part of the pickled state (Ray pickles this object into workers).
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(self._uri, auth=self._auth)
        return self._driver

    @driver.setter
    def driver(self, value) -> None:
        self._driver = value

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        state["_driver"] = None
        return state

    def write(self, batch: List[Dict[str, Any]]):
        """
        Called by Ray Data `write_datasource`.
        Receives a list of rows (dicts).
        """
        # 1. Flatten the batch into lists of all nodes and edges
        all_nodes = []
        all_edges = []

        for row in batch:
            # Each row corresponds to a text chunk
            if "graph_nodes" in row:
                all_nodes.extend(row["graph_nodes"])
            if "graph_edges" in row:
                all_edges.extend(row["graph_edges"])

        if not all_nodes and not all_edges:
            return

        # 2. Execute Batch Write Transaction
        with self.driver.session() as session:
            session.execute_write(
                self._merge_graph_data, all_nodes, all_edges, self.tenant_id
            )

    @staticmethod
    def _merge_graph_data(tx, nodes, edges, tenant_id):
        """
        Cypher query to idempotent MERGE (Upsert) data.
        All nodes and edges are tagged with tenant_id.
        """
        # 1. Merge Nodes — set tenant_id on each entity
        cypher_nodes = """
        UNWIND $nodes AS n
        MERGE (node:Entity {name: n.id, tenant_id: $tenant_id})
        SET node.type = n.type
        """
        tx.run(cypher_nodes, nodes=nodes, tenant_id=tenant_id)

        # 2. Merge Edges — match within same tenant
        cypher_edges = """
        UNWIND $edges AS e
        MATCH (source:Entity {name: e.source, tenant_id: $tenant_id})
        MATCH (target:Entity {name: e.target, tenant_id: $tenant_id})
        MERGE (source)-[r:RELATED {type: e.type}]->(target)
        """
        tx.run(cypher_edges, edges=edges, tenant_id=tenant_id)
