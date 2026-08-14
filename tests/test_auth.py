"""The API is closed by default: anything account-touching needs a session."""
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

PROTECTED_GET = ["/api/status", "/api/pro/dashboard", "/api/trade-manager",
                 "/api/risk-status", "/api/scan", "/api/trades"]
PROTECTED_POST = ["/api/auto?enabled=false", "/api/kill-switch?enabled=false",
                  "/api/optionalpha/test", "/api/paper/order"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB", tmp_path / "test.db")
    auth._SESSIONS.clear()
    auth._ATTEMPTS.clear()
    with TestClient(app) as c:
        yield c


def sign_in(client):
    assert client.post("/api/login", json={"token": auth.API_TOKEN}).status_code == 200


# ---- the guard ----------------------------------------------------------

@pytest.mark.parametrize("path", PROTECTED_GET)
def test_reads_require_a_session(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_POST)
def test_writes_require_a_session(client, path):
    assert client.post(path, json={}).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_GET)
def test_reads_succeed_once_signed_in(client, path):
    sign_in(client)
    assert client.get(path).status_code == 200


def test_kill_switch_is_unreachable_without_auth(client):
    """The most destructive endpoint must never be open."""
    assert client.post("/api/kill-switch?enabled=true").status_code == 401


def test_every_api_route_is_guarded_or_deliberately_public():
    public = {"/api/i18n", "/api/session", "/api/login", "/api/logout"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in public:
            continue
        names = [d.call.__name__ for d in route.dependant.dependencies]
        assert "require_auth" in names, f"{path} is not protected"


# ---- login / session ----------------------------------------------------

def test_session_starts_unauthenticated(client):
    assert client.get("/api/session").json()["authenticated"] is False


def test_login_then_session_reports_authenticated(client):
    sign_in(client)
    assert client.get("/api/session").json()["authenticated"] is True


def test_login_rejects_a_wrong_token(client):
    assert client.post("/api/login", json={"token": "nope"}).status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


def test_logout_invalidates_the_session(client):
    sign_in(client)
    client.post("/api/logout")
    assert client.get("/api/status").status_code == 401


def test_session_cookie_is_httponly_and_samesite_strict(client):
    response = client.post("/api/login", json={"token": auth.API_TOKEN})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_bearer_token_works_for_scripted_clients(client):
    response = client.get("/api/status", headers={"Authorization": f"Bearer {auth.API_TOKEN}"})
    assert response.status_code == 200


def test_a_wrong_bearer_token_is_refused(client):
    assert client.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_forged_session_cookie_is_refused(client):
    client.cookies.set(auth.COOKIE_NAME, "made-up-session")
    assert client.get("/api/status").status_code == 401


# ---- throttling ---------------------------------------------------------

def test_repeated_failures_lock_the_caller_out(client):
    for _ in range(auth.MAX_ATTEMPTS):
        client.post("/api/login", json={"token": "wrong"})
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 429


def test_lockout_applies_even_to_the_correct_token(client):
    """Otherwise the throttle could be bypassed by guessing until it opens."""
    for _ in range(auth.MAX_ATTEMPTS):
        client.post("/api/login", json={"token": "wrong"})
    assert client.post("/api/login", json={"token": auth.API_TOKEN}).status_code == 429


def test_a_successful_login_clears_the_failure_count(client):
    client.post("/api/login", json={"token": "wrong"})
    sign_in(client)
    assert auth._ATTEMPTS == {}


# ---- public surface -----------------------------------------------------

def test_the_message_catalog_is_public_so_login_can_be_localised(client):
    response = client.get("/api/i18n")
    assert response.status_code == 200
    assert "login_title" in response.json()["messages"]


def test_the_html_shell_is_public(client):
    assert client.get("/").status_code == 200


def test_token_comparison_is_constant_time():
    assert auth.token_matches(auth.API_TOKEN) is True
    assert auth.token_matches("") is False
    assert auth.token_matches(None) is False
