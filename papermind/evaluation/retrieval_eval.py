import math
from collections import defaultdict


def retrieval_metrics(
    ranked_ids: list[str], gold_ids: list[str], ks=(1, 3, 5, 10)
) -> dict[str, float]:
    if any(k <= 0 for k in ks):
        raise ValueError("K must be positive")
    gold = set(gold_ids)
    if not gold:
        raise ValueError("Retrieval relevance metrics require at least one gold source")
    ranked = list(dict.fromkeys(ranked_ids))
    result = {}
    first = next((i for i, item in enumerate(ranked, 1) if item in gold), None)
    result["mrr"] = 1 / first if first else 0.0
    for k in ks:
        found = len(set(ranked[:k]) & gold)
        result[f"hit@{k}"] = float(found > 0)
        result[f"recall@{k}"] = found / len(gold)
        dcg = sum(
            1 / math.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in gold
        )
        ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
        result[f"ndcg@{k}"] = dcg / ideal
    return result


def aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    totals = defaultdict(float)
    for row in rows:
        for key, value in row.items():
            totals[key] += value
    return {key: value / len(rows) for key, value in totals.items()}
