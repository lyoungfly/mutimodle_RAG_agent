import base64
import json

import httpx
import pytest

from papermind.errors import ModelResponseError
from papermind.models import Document, Figure
from papermind.multimodal.vlm import (
    CompatibleVLM,
    VisionResult,
    enrich_figures,
    validate_result,
)


def test_vlm_sends_actual_png_and_validates_structured_response(monkeypatch):
    from test_llm import install_transport

    def handler(request):
        body = json.loads(request.content)
        message = body["messages"][1]["content"]
        assert body["model"] == "vision-test"
        assert (
            base64.b64decode(message[1]["image_url"]["url"].split(",")[1])
            == b"PNG-test-data"
        )
        response = {
            "description": "Two connected blocks.",
            "tables": [
                {"headers": ["Model", "PSNR"], "rows": [["A", "27.3"]]},
            ],
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(response)}}]}
        )

    install_transport(monkeypatch, handler)
    result = CompatibleVLM("http://vision/v1", "vision-test").analyze(
        b"PNG-test-data", "Figure 1", "Context"
    )
    assert result.description == "Two connected blocks."
    assert result.tables[0]["rows"] == [["A", "27.3"]]


@pytest.mark.parametrize(
    "result",
    [
        {"description": ""},
        {"description": 123},
        {"description": "x", "tables": "invalid"},
        {"description": "x", "tables": [{"headers": ["a", "b"], "rows": [["1"]]}]},
        {"description": "x", "tables": [{"headers": ["a"], "rows": [[1]]}]},
        {"description": "x", "tables": [{"headers": [], "rows": []}]},
    ],
)
def test_invalid_visual_outputs_are_rejected(result):
    with pytest.raises(ModelResponseError):
        validate_result(result)


def test_service_failures_are_bounded_and_preserve_source():
    class FailingVision:
        name = "failing"
        calls = 0

        def analyze(self, *args):
            self.calls += 1
            raise RuntimeError("temporary failure")

    model = FailingVision()
    document = Document(
        "d", "D", figures=[Figure(f"fig_{i}", 1, asset_id="asset") for i in range(8)]
    )
    enrich_figures(document, {"asset": b"image"}, model)
    assert model.calls == 3
    assert [figure.analysis_status for figure in document.figures[:3]] == ["failed"] * 3
    assert document.figures[3].analysis_status == "skipped"
    assert all(
        figure.asset_id == "asset" and not figure.visual_description
        for figure in document.figures
    )


def test_visual_tables_keep_provenance_and_calls_are_limited():
    class Vision:
        name = "test-only"

        def analyze(self, *args):
            return VisionResult(
                "A result table",
                [{"headers": ["Model", "Params"], "rows": [["A", "4M"]]}],
            )

    document = Document(
        "d",
        "D",
        figures=[
            Figure("fig_1", 3, asset_id="asset"),
            Figure("fig_2", 4, asset_id="asset"),
        ],
    )
    enrich_figures(document, {"asset": b"image"}, Vision(), max_calls=1)
    assert document.tables[0].source_figure_id == "fig_1"
    assert document.tables[0].extraction_method == "vlm"
    assert document.tables[0].page == 3
    assert document.figures[1].analysis_status == "skipped"
