import json

import pytest

from app.resolution.evaluate import DEFAULT_CORPUS, run_evaluation


def test_offline_evaluation_is_redacted_and_repeatable_shape():
    report = run_evaluation(DEFAULT_CORPUS)
    assert report["schema_version"] == "llm-053-v1"
    assert set(report["paths"]) == {"deterministic", "scripted_model"}
    assert report["corpus_cases"] == 12
    assert report["paths"]["scripted_model"]["output_tokens"] > 0
    assert "ERR_EXPORT_504" not in json.dumps(report)


def test_malformed_corpus_fails_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        run_evaluation(path)
