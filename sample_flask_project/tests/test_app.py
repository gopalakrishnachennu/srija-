import pytest

from sample_flask_project.app import create_app


@pytest.fixture()
def app():
    return create_app({"TESTING": True, "SECRET_KEY": "test-secret"})


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username="admin", password="admin123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_home_redirects_anonymous_user_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_login_page_contains_accessible_form(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'id="username"' in response.data
    assert b'id="password"' in response.data
    assert b"Sign in" in response.data


def test_valid_login_creates_session_and_opens_dashboard(client):
    response = login(client)
    assert response.status_code == 200
    assert b"Good to see you, admin" in response.data
    with client.session_transaction() as session:
        assert session["user"] == "admin"


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin", "wrong"), ("unknown", "admin123")],
)
def test_invalid_credentials_are_rejected(client, username, password):
    response = login(client, username, password)
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data
    with client.session_transaction() as session:
        assert "user" not in session


def test_empty_credentials_show_validation_error(client):
    response = login(client, "", "")
    assert b"Username and password are required" in response.data


def test_dashboard_requires_authentication(client):
    response = client.get("/dashboard", follow_redirects=True)
    assert response.status_code == 200
    assert b"Please sign in to view the dashboard" in response.data
    assert b"Welcome back" in response.data


def test_logged_in_user_is_not_shown_login_again(client):
    login(client)
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_logout_clears_session_and_protects_dashboard(client):
    login(client)
    response = client.post("/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"You have been signed out" in response.data

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 302
    assert dashboard.headers["Location"].endswith("/login")
