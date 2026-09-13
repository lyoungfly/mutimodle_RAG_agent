import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from papermind.api.main import create_app
from papermind.api.settings_routes import probe
from papermind.config import Settings
from papermind.model_api import APIEndpoint, normalize_url
from papermind.service import PaperMindService


def connection(**changes):
    return {
        "enabled": True,
        "base_url": "https://models.example/v1",
        "model": "test-model",
        "api_key": None,
        **changes,
    }


def configuration(**changes):
    return {"llm": connection(**changes), "vlm": connection(enabled=False, model="")}


def test_settings_save_redaction_runtime_restart_and_clear(tmp_path):
    settings = Settings(data_dir=tmp_path, llm_api_key="old-secret")
    service = PaperMindService(settings)
    service.llm = object()
    with TestClient(create_app(service=service)) as client:
        page = client.get("/settings")
        assert page.status_code == 200 and "怎么填" in page.text
        assert client.get("/api/settings").headers["cache-control"] == "no-store"
        body = configuration(
            api_key="new-secret", base_url="https://models.example/v1/chat/completions/"
        )
        result = client.put("/api/settings", json=body)
        assert result.status_code == 200
        assert "new-secret" not in result.text and "old-secret" not in result.text
        assert result.json()["llm"]["has_api_key"]
        assert service.settings.llm_model == "test-model" and service.llm is None
        assert service.settings.llm_base_url == "https://models.example/v1"
        service._load_models()
        assert service.llm.api_key == "new-secret"
        restarted = PaperMindService(settings)
        assert restarted.settings.llm_api_key == "new-secret"
        assert restarted.settings.llm_model == "test-model"
        assert (
            client.put(
                "/api/settings", json=configuration(model="second-model")
            ).status_code
            == 200
        )
        assert service.settings.llm_api_key == "new-secret"
        assert (
            client.put(
                "/api/settings", json=configuration(enabled=False, clear_api_key=True)
            ).status_code
            == 200
        )
        assert not service.settings.llm_model and not service.settings.llm_api_key
        assert not client.get("/health").json()["llm_configured"]
        assert not PaperMindService(settings).settings.llm_model


def test_configuration_write_failure_preserves_live_and_disk(tmp_path, monkeypatch):
    service = PaperMindService(Settings(data_dir=tmp_path))
    service.configure_apis(configuration(api_key="original"))
    before = service.api_config_store.path.read_bytes()

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(service.api_config_store, "save", fail)
    with pytest.raises(OSError):
        service.configure_apis(configuration(api_key="replacement"))
    assert service.settings.llm_api_key == "original"
    assert service.api_config_store.path.read_bytes() == before


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com/v1",
        "https://example.com?key=secret",
        "file:///tmp/key",
        "https://example.com:99999",
        "https://example.com/#fragment",
        "https://exa mple.com",
    ],
)
def test_invalid_base_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_changed_host_cannot_reuse_saved_key_and_invalid_input_is_redacted(tmp_path):
    service = PaperMindService(Settings(data_dir=tmp_path))
    service.configure_apis(configuration(api_key="saved-secret"))
    with TestClient(create_app(service=service)) as client:
        result = client.post(
            "/api/settings/test/llm",
            json=connection(base_url="https://other.example/v1"),
        )
        assert result.status_code == 422 and "重新填写" in result.json()["detail"]
        assert "saved-secret" not in result.text
        body = configuration(api_key="sensitive" * 1000)
        result = client.put("/api/settings", json=body)
        assert result.status_code == 422 and "sensitive" not in result.text
        assert not service.api_config_store.path.read_text().count("sensitive")


def test_cross_site_and_remote_configuration_is_rejected(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        for path in ("/settings", "/api/settings"):
            assert (
                client.get(
                    path, headers={"Origin": "https://other.example"}
                ).status_code
                == 403
            )
            assert client.get(path, headers={"Host": "evil.example"}).status_code == 403
        assert (
            client.put(
                "/api/settings",
                json=configuration(),
                headers={"Origin": "https://other.example"},
            ).status_code
            == 403
        )
    with TestClient(app, client=("192.168.1.9", 1234)) as client:
        assert client.get("/api/settings").status_code == 403


def mock_upstream(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        "papermind.api.settings_routes.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_connection_probes_send_expected_payload_without_echoing_secrets(monkeypatch):
    seen = []

    def handler(request):
        assert request.headers["Authorization"] == "Bearer private-key"
        assert str(request.url) == "https://models.example/v1/chat/completions"
        data = json.loads(request.content)
        seen.append(data["messages"][0]["content"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "private-key"}}]}
        )

    mock_upstream(monkeypatch, handler)
    endpoint = APIEndpoint(
        True, "https://models.example/v1", "test-model", "private-key"
    )
    for kind in ("llm", "vlm"):
        result = probe(endpoint, kind)
        assert result["ok"] and "private-key" not in str(result)
    assert seen[0] == "Reply with OK."
    image = base64.b64decode(seen[1][1]["image_url"]["url"].split(",")[1])
    with Image.open(io.BytesIO(image)) as picture:
        assert picture.size == (32, 32)
        picture.verify()


@pytest.mark.parametrize(
    "code,message",
    [
        (401, "密钥"),
        (403, "权限"),
        (404, "地址"),
        (429, "额度"),
        (500, "HTTP 500"),
        (302, "HTTP 302"),
    ],
)
def test_connection_http_errors_are_actionable_and_redacted(monkeypatch, code, message):
    def handler(request):
        return httpx.Response(
            code, text="secret-key", headers={"location": "https://other.example"}
        )

    mock_upstream(monkeypatch, handler)
    result = probe(
        APIEndpoint(True, "https://models.example", "m", "secret-key"), "llm"
    )
    assert (
        not result["ok"]
        and message in result["message"]
        and "secret-key" not in str(result)
    )


def test_test_endpoint_does_not_save_configuration(tmp_path, monkeypatch):
    from papermind.api import settings_routes

    monkeypatch.setattr(
        settings_routes, "probe", lambda *args: {"ok": True, "message": "test"}
    )
    service = PaperMindService(Settings(data_dir=tmp_path))
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/settings/test/llm", json=connection(api_key="private-key")
        )
        assert response.status_code == 200 and response.json()["ok"]
        assert (
            not service.settings.llm_model
            and not service.api_config_store.path.exists()
        )
