import pytest

from app import app


@pytest.fixture()
def client():
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as client:
        yield client


def test_login_page_opens(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Login" in response.data


def test_valid_login_opens_dashboard(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome, admin" in response.data


def test_invalid_login_shows_error(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "wrong"}
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

