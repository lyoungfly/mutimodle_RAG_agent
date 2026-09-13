import math
import re
from collections import Counter, defaultdict

from papermind.models import Chunk, SearchFilter, SearchHit


def tokenize(text: str) -> list[str]:
    tokens = re.findall(
        r"[a-z0-9]+(?:[._-][a-z0-9]+)*|[\u4e00-\u9fff]+", text.casefold()
    )
    result = []
    for token in tokens:
        if "\u4e00" <= token[0] <= "\u9fff":
            result.extend(token)
            result.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            result.append(token)
    return result


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("Invalid BM25 parameters")
        self.chunks = tuple(chunks)
        self.k1, self.b = k1, b
        self.lengths = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, chunk in enumerate(chunks):
            tokens = tokenize(f"{chunk.section} {chunk.content}")
            self.lengths.append(len(tokens))
            for term, frequency in Counter(tokens).items():
                self.postings[term].append((index, frequency))
        self.average_length = sum(self.lengths) / len(chunks) if chunks else 1

    def search(
        self, query: str, k: int = 20, filters: SearchFilter | None = None
    ) -> list[SearchHit]:
        if k <= 0:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            postings = self.postings.get(term, ())
            idf = math.log(
                1 + (len(self.chunks) - len(postings) + 0.5) / (len(postings) + 0.5)
            )
            for index, frequency in postings:
                if filters and not filters.matches(self.chunks[index]):
                    continue
                norm = (
                    1
                    - self.b
                    + self.b * self.lengths[index] / (self.average_length or 1)
                )
                scores[index] += (
                    idf * frequency * (self.k1 + 1) / (frequency + self.k1 * norm)
                )
        ranked = sorted(scores, key=lambda i: (-scores[i], self.chunks[i].chunk_id))[:k]
        return [
            SearchHit(self.chunks[i], scores[i], {"bm25": scores[i]}) for i in ranked
        ]
