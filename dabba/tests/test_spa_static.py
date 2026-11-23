"""Client-side routes (/c/<id>, /agents) must load the app, not 404."""

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from dabba.api.server import SPAStaticFiles


@pytest.fixture()
def client(tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("js")
    app = Starlette()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True))
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/c/abc-123", "/agents", "/connectors/"])
def test_app_routes_serve_index(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "app" in response.text


def test_real_files_still_served(client):
    assert client.get("/assets/app.js").text == "js"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/v1/unknown"])
def test_missing_files_and_api_paths_still_404(client, path):
    assert client.get(path).status_code == 404
