from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.infrastructure.object_storage import LocalObjectStorage
from app.storage_routes import router


def test_signed_local_upload_and_download_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_storage_driver", "local")
    monkeypatch.setattr(settings, "object_storage_local_path", str(tmp_path))
    monkeypatch.setattr(settings, "object_storage_local_public_url", "http://testserver")
    monkeypatch.setattr(settings, "object_storage_signing_secret", "unit-test-secret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    storage = LocalObjectStorage()

    upload = urlsplit(storage.upload_url("workspaces/w/file", "text/plain", 5))
    response = client.put(f"{upload.path}?{upload.query}", content=b"hello", headers={"Content-Type": "text/plain"})
    assert response.status_code == 204

    download = urlsplit(storage.download_url("workspaces/w/file", "hello.txt"))
    response = client.get(f"{download.path}?{download.query}")
    assert response.status_code == 200
    assert response.content == b"hello"
    assert 'filename="hello.txt"' in response.headers["content-disposition"]

    tampered = client.put(
        f"{upload.path}?{upload.query.replace('byte_size=5', 'byte_size=6')}",
        content=b"hello!", headers={"Content-Type": "text/plain"},
    )
    assert tampered.status_code == 403
