import pytest

from papermind.answering import generate_answer
from papermind.models import Chunk, SearchHit


class StubLLM:
    def __init__(self, response):
        self.response = response

    def answer(self, question, evidence):
        return self.response


@pytest.mark.parametrize("citations", [[], [0], [2], [True], ["1"], None])
def test_invalid_citations_never_reach_user(citations):
    hits = [SearchHit(Chunk("d:0", "d", "Evidence", 1, "Method"), 1)]
    llm = StubLLM(
        {"abstain": False, "claims": [{"text": "Fact", "citations": citations}]}
    )
    with pytest.raises(ValueError, match="citation"):
        generate_answer("Question", hits, [{"id": 1}], llm)


def test_valid_citation_and_model_refusal():
    hits = [SearchHit(Chunk("d:0", "d", "Evidence", 1, "Method"), 1)]
    result = generate_answer(
        "Question",
        hits,
        [{"id": 1}],
        StubLLM({"abstain": False, "claims": [{"text": "Fact", "citations": [1]}]}),
    )
    assert result["answer"] == "Fact [1]"
    assert result["mode"] == "generated"
    assert generate_answer("Question", hits, [{"id": 1}], StubLLM({"abstain": True}))[
        "abstained"
    ]
