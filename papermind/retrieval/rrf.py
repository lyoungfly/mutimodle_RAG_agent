from papermind.models import SearchHit


def reciprocal_rank_fusion(
    rankings: list[list[SearchHit]], k: int = 60
) -> list[SearchHit]:
    if k < 0:
        raise ValueError("RRF k must be non-negative")
    fused: dict[str, SearchHit] = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit.chunk.chunk_id
            if key in seen:
                continue
            seen.add(key)
            if key not in fused:
                fused[key] = SearchHit(hit.chunk, 0, {})
            fused[key].score += 1 / (k + rank)
            fused[key].scores.update(hit.scores)
    for hit in fused.values():
        hit.scores["rrf"] = hit.score
    return sorted(fused.values(), key=lambda h: (-h.score, h.chunk.chunk_id))
