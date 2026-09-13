from fastapi.testclient import TestClient

from papermind.api.main import create_app
from papermind.config import Settings


def test_collection_discovery_counts_and_workspace_assets(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/collections").json() == []
        for name, collection in [
            ("a.txt", "vision"),
            ("b.txt", "vision"),
            ("c.txt", "other"),
        ]:
            assert (
                client.post(
                    "/documents/upload",
                    data={"collection_id": collection},
                    files={"file": (name, name.encode())},
                ).status_code
                == 201
            )
        assert client.get("/collections").json() == [
            {"collection_id": "other", "document_count": 1},
            {"collection_id": "vision", "document_count": 2},
        ]
        assert (
            len(client.get("/documents", params={"collection_id": "vision"}).json())
            == 2
        )
        for path in (
            "/",
            "/settings",
            "/static/workspace.css",
            "/static/workspace-ui.js",
            "/static/app.js",
        ):
            assert client.get(path).status_code == 200
