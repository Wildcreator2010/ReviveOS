import pytest
from fastapi.testclient import TestClient
from revive_api.config import Config
from revive_api.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app(Config()))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5432",
        "http://169.254.169.254/latest/meta-data",
        "http://github.com/redirect-to-private",
        "ext::sh -c id",
    ],
)
def test_ssrf_attack_urls_are_rejected(client, url):
    response = client.post("/projects", json={"repository_url": url})
    assert response.status_code == 400
