import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from papermind.models import SearchFilter
from papermind.service import PaperMindService

from .retrieval_eval import aggregate, retrieval_metrics


@dataclass(frozen=True)
class RetrievalExample:
    id: str
    question: str
    gold_chunk_ids: list[str]
    collection_id: str = "default"
    category: str = "fact_qa"
    filters: dict = field(default_factory=dict)


def load_examples(path: Path) -> list[RetrievalExample]:
    examples = [
        RetrievalExample(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not examples or len({example.id for example in examples}) != len(examples):
        raise ValueError("Benchmark must contain examples with unique IDs")
    return examples


def run_benchmark(
    service: PaperMindService,
    examples: list[RetrievalExample],
    modes=("bm25", "dense", "hybrid", "hybrid_rerank"),
    k: int = 10,
) -> dict:
    if not examples:
        raise ValueError("Benchmark requires at least one example")
    if k < 10:
        raise ValueError("k must be at least 10 to report metrics through Recall@10")
    corpora = {}
    for example in examples:
        if example.collection_id not in corpora:
            _, chunks, _, _ = service.store.snapshot(example.collection_id)
            corpora[example.collection_id] = {chunk.chunk_id for chunk in chunks}
        if not set(example.gold_chunk_ids).issubset(corpora[example.collection_id]):
            raise ValueError(
                f"Unknown gold chunk in example {example.id}; check dataset/index versions"
            )
    result = {
        "sample_count": len(examples),
        "retrieval_depth": k,
        "runs": {},
        "embedding_model": service.settings.embedding_model,
        "reranker_model": service.settings.reranker_model,
        "chunk_size_chars": service.settings.chunk_size,
    }
    for mode in modes:
        rows, details, timings = [], [], []
        try:
            for example in examples:
                start = time.perf_counter()
                hits = service.search(
                    example.question,
                    example.collection_id,
                    k,
                    SearchFilter(**example.filters) if example.filters else None,
                    mode,
                )
                timings.append(time.perf_counter() - start)
                ids = [hit.chunk.chunk_id for hit in hits]
                if example.gold_chunk_ids:
                    metrics = retrieval_metrics(ids, example.gold_chunk_ids)
                    rows.append(metrics)
                else:
                    metrics = {"empty_retrieval": float(not ids)}
                details.append(
                    {
                        "id": example.id,
                        "category": example.category,
                        "ranked_ids": ids,
                        "metrics": metrics,
                    }
                )
            result["runs"][mode] = {
                "status": "completed",
                "metrics": aggregate(rows),
                "relevance_sample_count": len(rows),
                "unanswerable_sample_count": len(examples) - len(rows),
                "mean_query_seconds": sum(timings) / len(timings),
                "examples": details,
            }
        except RuntimeError as exc:
            result["runs"][mode] = {"status": "unavailable", "reason": str(exc)}
    return result


def evaluate_file(service: PaperMindService, dataset: Path, output: Path) -> dict:
    result = run_benchmark(service, load_examples(dataset))
    result["dataset_sha256"] = hashlib.sha256(dataset.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
