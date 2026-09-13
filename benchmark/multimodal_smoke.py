"""用明确标注的合成 PDF 验证正在运行的服务，不用于报告论文集准确率。"""

import argparse
import json
from pathlib import Path

import httpx
import pymupdf


def fixture() -> bytes:
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((40, 40), "Synthetic V2 validation document", fontsize=16)
        page.insert_text((40, 80), "1 Method")
        page.insert_text(
            (40, 105), "Red feature blocks feed a blue reconstruction block."
        )
        page.draw_rect((40, 140, 180, 220), color=(1, 0, 0), fill=(1, 0.2, 0.2))
        page.draw_line((180, 180), (240, 180), width=2)
        page.draw_rect((240, 140, 380, 220), color=(0, 0, 1), fill=(0.2, 0.2, 1))
        page.insert_text(
            (40, 247), "Figure 1. Feature extraction and reconstruction architecture."
        )
        page.insert_text((40, 310), "2 Results")
        page.insert_text(
            (40, 345), "Table 1. Synthetic model comparison (not research results)."
        )
        for x in (40, 200, 360):
            page.draw_line((x, 365), (x, 455))
        for y in (365, 395, 425, 455):
            page.draw_line((40, y), (360, y))
        for r, row in enumerate(
            (("Model", "PSNR (dB)"), ("Model-A", "27.30"), ("Model-B", "28.10"))
        ):
            for c, cell in enumerate(row):
                page.insert_text((45 + c * 160, 385 + r * 30), cell)
        return pdf.tobytes(no_new_id=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    output = Path("data")
    output.mkdir(exist_ok=True)
    content = fixture()
    (output / "v2-synthetic.pdf").write_bytes(content)
    collection = "v2_smoke"
    with httpx.Client(base_url=args.url, timeout=300) as client:

        def checked(response):
            response.raise_for_status()
            return response.json()

        upload = checked(
            client.post(
                "/documents/upload",
                data={"collection_id": collection},
                files={"file": ("v2-synthetic.pdf", content, "application/pdf")},
            )
        )
        doc_id = upload["document_id"]
        indexed = checked(
            client.post(
                "/documents/index",
                json={"document_id": doc_id, "collection_id": collection},
            )
        )
        assert indexed["figure_count"] == 1 and indexed["table_count"] == 1
        gallery = checked(
            client.get(
                f"/documents/{doc_id}/visuals", params={"collection_id": collection}
            )
        )
        assert gallery["tables"][0]["rows"] == [
            ["Model-A", "27.30"],
            ["Model-B", "28.10"],
        ]
        for item in gallery["figures"] + gallery["tables"]:
            path = f"/documents/{doc_id}/assets/{item['asset_id']}"
            response = client.get(path, params={"collection_id": collection})
            assert response.status_code == 200 and response.content.startswith(
                b"\x89PNG"
            )
            assert (
                client.get(path, params={"collection_id": "default"}).status_code == 404
            )
        answers = {}
        for kind, question in (
            ("table", "Model-B PSNR"),
            ("figure", "feature extraction reconstruction architecture"),
        ):
            answer = checked(
                client.post(
                    "/chat",
                    json={
                        "collection_id": collection,
                        "question": question,
                        "filters": {"content_type": kind},
                    },
                )
            )
            assert answer["sources"] and answer["sources"][0].get(kind)
            assert answer["sources"][0].get("image_url")
            answers[kind] = answer
        result = {
            "dataset_kind": "synthetic-smoke-only",
            "index": indexed,
            "answers": answers,
        }
        (output / "v2-smoke-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {"collection": collection, "index": indexed, "status": "passed"},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
