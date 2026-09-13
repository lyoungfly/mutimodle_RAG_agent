import pytest
from conftest import ingest

from papermind.evaluation.benchmark import RetrievalExample, run_benchmark
from papermind.evaluation.retrieval_eval import retrieval_metrics


def test_multigold_recall_is_not_hit_rate():
    metrics = retrieval_metrics(["a", "a", "c", "b"], ["a", "b"])
    assert metrics["hit@1"] == 1
    assert metrics["recall@1"] == 0.5
    assert metrics["recall@3"] == 1
    assert metrics["mrr"] == 1
    assert 0 < metrics["ndcg@3"] < 1
    with pytest.raises(ValueError):
        retrieval_metrics([], [])


def test_benchmark_does_not_invent_unconfigured_results(service):
    doc_id = ingest(service, "Urban100 PSNR 27.38")
    result = run_benchmark(
        service,
        [
            RetrievalExample("q1", "Urban100", [f"{doc_id}:0"]),
            RetrievalExample("q2", "unrelatedword", [], category="unanswerable"),
        ],
    )
    assert result["runs"]["bm25"]["metrics"]["recall@1"] == 1
    assert result["runs"]["bm25"]["unanswerable_sample_count"] == 1
    assert result["runs"]["dense"]["status"] == "unavailable"
    with pytest.raises(ValueError, match="Unknown gold"):
        run_benchmark(service, [RetrievalExample("bad", "test", ["missing"])])
