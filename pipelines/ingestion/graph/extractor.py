# pipelines/ingestion/graph/extractor.py
import json
from textwrap import dedent
from typing import Any, Dict

import httpx

from pipelines.ingestion.graph.schema import GraphSchema


class GraphExtractor:
    """
    Ray Actor Class for Graph Extraction.
    Calls the internal LLM Service to extract entities.
    """
    def __init__(self):
        # Point to the internal Ray Serve LLM endpoint
        # We use the internal K8s DNS name
        self.llm_endpoint = "http://ray-serve-llm:8000/llm/chat"
        self.client = httpx.Client(timeout=60.0) # Long timeout for reasoning

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a batch of text chunks.
        """
        nodes_list = []
        edges_list = []

        # Iterate through chunks in the batch
        for text in batch["text"]:
            try:
                # 1. Construct Prompt
                prompt = dedent(
                    f"""
                    {GraphSchema.get_system_prompt()}

                    Input Text:
                    {text}
                    """
                ).strip()

                # 2. Call LLM (Llama-3-70B)
                response = self.client.post(
                    self.llm_endpoint,
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,  # Deterministic output
                        "max_tokens": 1024,
                    }
                )
                response.raise_for_status()

                # 3. Parse JSON Output
                # We assume the model returns valid JSON (guaranteed by constrained decoding or post-processing)
                content = response.json()["choices"][0]["message"]["content"]
                graph_data = json.loads(content)

                # 4. Append to results
                nodes_list.append(graph_data.get("nodes", []))
                edges_list.append(graph_data.get("edges", []))

            except Exception as e:
                # Log error but don't crash the pipeline; return empty graph for this chunk
                print(f"Graph extraction failed for chunk: {e}")
                nodes_list.append([])
                edges_list.append([])

        # Add graph data to the batch
        batch["graph_nodes"] = nodes_list
        batch["graph_edges"] = edges_list
        return batch


class AzureOpenAIGraphExtractor:
    """
    Graph extraction with the keyless Azure OpenAI chat deployment (``INGEST_GRAPH_PROVIDER=azure_openai``).

    Same output as ``GraphExtractor`` (``graph_nodes`` / ``graph_edges`` per chunk) and the same behaviour on a bad
    chunk: log it and emit an empty graph rather than failing the batch. Newer chat models take
    ``max_completion_tokens`` (their reasoning tokens count against it, so it is generous) and only the default
    temperature, so neither ``max_tokens`` nor ``temperature`` is sent.
    """

    def __init__(self):
        import os

        self.deployment = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-6-luna")
        self.max_completion_tokens = int(os.getenv("INGEST_GRAPH_MAX_COMPLETION_TOKENS", "4096"))
        self.client = None

    def _ensure_client(self):
        if self.client is not None:
            return
        import os

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT required for the Azure OpenAI graph extractor")
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_ad_token_provider=get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            ),
            timeout=120.0,
        )

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        nodes_list, edges_list = [], []
        for text in batch["text"]:
            try:
                prompt = dedent(
                    f"""
                    {GraphSchema.get_system_prompt()}

                    Input Text:
                    {text}
                    """
                ).strip()
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=self.max_completion_tokens,
                    response_format={"type": "json_object"},
                )
                graph_data = json.loads(response.choices[0].message.content)
                nodes_list.append(graph_data.get("nodes", []))
                edges_list.append(graph_data.get("edges", []))
            except Exception as e:  # one bad chunk must not fail the batch
                print(f"Graph extraction failed for chunk: {e}")
                nodes_list.append([])
                edges_list.append([])
        batch["graph_nodes"] = nodes_list
        batch["graph_edges"] = edges_list
        return batch


def select_graph_extractor(env):
    """The graph extractor class for ``INGEST_GRAPH_PROVIDER``: ``ray`` (default, the Ray Serve LLM), ``azure_openai``
    (keyless), or ``None`` for ``none`` (no graph is built)."""
    provider = (env.get("INGEST_GRAPH_PROVIDER") or "ray").strip().lower()
    if provider == "ray":
        return GraphExtractor
    if provider == "azure_openai":
        return AzureOpenAIGraphExtractor
    if provider == "none":
        return None
    raise ValueError(f"INGEST_GRAPH_PROVIDER must be 'ray', 'azure_openai' or 'none', got {provider!r}")
