import pytest

import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """give each test a fresh library app with its own seeded database"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return app.create_app().test_client()

def test_home_page_reports_the_app_is_up(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"

def test_unknown_url_returns_json_not_html(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.get_json() == {"error": "not found"}

def test_adding_an_invalid_game_returns_400_with_the_reason(client):
    response = client.post("/games", json={"title": "Dune"})
    assert response.status_code == 400
    assert "missing field" in response.get_json()["error"]

def test_get_game_returns_its_id_and_title(client):
    response = client.get("/games/1")
    assert response.status_code == 200
    assert response.get_json() == {"id": 1, "title": "Catan"}

def test_get_game_returns_404_for_an_unknown_id(client):
    response = client.get("/games/999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "no game with id 999"}