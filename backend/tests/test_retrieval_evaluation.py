import json
from pathlib import Path

from app.retrieval.evaluation import recall_at_k, reciprocal_rank


FIXTURE = Path(__file__).parent / "fixtures" / "retrieval_quality_cases.json"


def test_bilingual_quality_fixture_and_metrics_are_machine_readable():
    cases = json.loads(FIXTURE.read_text())

    assert {case["language"] for case in cases} == {"en", "zh"}
    assert all(case["query"] and case["relevant_node_ids"] for case in cases)
    assert recall_at_k(["a", "b", "c"], {"b", "c"}, 2) == 0.5
    assert recall_at_k(["a", "b", "c"], {"b", "c"}, 3) == 1.0
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == 1 / 3
