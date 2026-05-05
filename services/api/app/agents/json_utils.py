# services/api/app/agents/json_utils.py
"""Robust JSON extraction from LLM responses."""
import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """
    Extract a JSON object from LLM output that may contain markdown
    code fences, explanatory text, or other non-JSON content.

    Tries in order:
      1. Direct json.loads (fastest path)
      2. Strip markdown ```json ... ``` fences
      3. Find first { ... } block via brace matching
    """
    if not text or not text.strip():
        raise ValueError("Empty response from LLM")

    text = text.strip()

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find first balanced { ... } block
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")
