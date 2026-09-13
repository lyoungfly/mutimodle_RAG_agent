from fastapi.testclient import TestClient

from papermind.api.main import create_app
from papermind.config import Settings


def test_upload_index_chat_source_and_ui(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        response = client.post(
            "/documents/upload",
            files={"file": ("paper.txt", b"Mamba achieves 27.38 PSNR")},
        )
        assert response.status_code == 201
        document_id = response.json()["document_id"]
        assert (
            client.post(
                "/documents/index", json={"document_id": document_id}
            ).status_code
            == 200
        )
        answer = client.post("/chat", json={"question": "Mamba"}).json()
        assert answer["sources"][0]["document_id"] == document_id
        chunk_id = answer["sources"][0]["chunk_id"]
        assert client.get(f"/sources/{chunk_id}").status_code == 200
        assert client.get(f"/sources/{chunk_id}?collection_id=other").status_code == 404
        assert (
            client.get(f"/documents/{document_id}/file").content
            == b"Mamba achieves 27.38 PSNR"
        )
        assert (
            client.post(
                "/chat", json={"question": "Mamba", "mode": "dense"}
            ).status_code
            == 503
        )
        assert client.post("/chat", json={"question": "   "}).status_code == 422
        assert client.post(
            "/chat", json={"question": "Mamba", "filters": {"document_ids": []}}
        ).json()["abstained"]


def test_overall_request_limit_without_content_length(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, max_upload_bytes=10))
    ) as client:

        def body():
            yield b" " * (1024 * 1024)
            yield b" " * 100

        response = client.post(
            "/chat", content=body(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413


def test_model_output_errors_are_upstream_failures(service):
    from conftest import ingest

    class BadLLM:
        def answer(self, question, evidence):
            return {"abstain": False, "claims": [{"text": "wrong", "citations": [99]}]}

    ingest(service, "Mamba architecture")
    service.llm = BadLLM()
    with TestClient(create_app(service=service)) as client:
        assert client.post("/chat", json={"question": "Mamba"}).status_code == 502


def test_upload_size_and_invalid_content(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, max_upload_bytes=10))
    ) as client:
        assert (
            client.post(
                "/documents/upload", files={"file": ("a.txt", b"a" * 11)}
            ).status_code
            == 413
        )
        assert (
            client.post("/documents/upload", files={"file": ("a.txt", b"")}).status_code
            == 422
        )
        assert (
            client.post(
                "/documents/upload", files={"file": ("a.exe", b"a")}
            ).status_code
            == 422
        )
