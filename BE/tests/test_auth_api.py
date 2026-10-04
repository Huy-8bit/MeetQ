"""User (Google) and admin (username/password) sign-in, per docs/auth-backend-contract.md.

Google ID tokens are signed with a local RSA key whose JWKS is served by a fake
fetcher, so the real verification path (signature, aud, iss, exp, email_verified)
runs without network access.
"""
import logging
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from server.service.auth import api as auth_api
from server.service.auth.cookies import ADMIN_COOKIE, USER_COOKIE
from server.service.auth.google import GoogleIdTokenVerifier
from server.service.auth.passwords import hash_password, verify_password
from server.service.gateway.app_state import app_state
from server.service.gateway.main import app
from tests.fake_mongo import FakeMongoDatabase

CLIENT_ID = "1234-test.apps.googleusercontent.com"
TRUSTED_ORIGIN = "http://localhost:3000"


def _rsa_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


PRIVATE_PEM, PUBLIC_PEM = _rsa_pem()
OTHER_PRIVATE_PEM, _ = _rsa_pem()
JWKS = {"keys": [{**jwk.construct(PUBLIC_PEM, "RS256").to_dict(), "kid": "k1", "use": "sig", "alg": "RS256"}]}


def google_token(*, private_pem=PRIVATE_PEM, kid="k1", **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1098765432",
        "email": "Huy@Example.com",
        "email_verified": True,
        "name": "Nguyen Gia Huy",
        "picture": "https://lh3.googleusercontent.com/a/photo",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


class _History:
    def __init__(self, db):
        self.db = db
        self.enabled = True


@pytest.fixture
def client(gateway_app, fake_settings):
    fake_settings.google_client_id = CLIENT_ID
    fake_settings.user_auth_required = True
    fake_settings.auth_cookie_secure = False  # TestClient talks plain http
    fake_settings.admin_username = "ops"
    fake_settings.admin_password = "correct horse battery"
    app_state.room_history = _History(FakeMongoDatabase())

    async def fetch_jwks():
        return JWKS, 3600

    app.dependency_overrides[auth_api.get_google_verifier] = lambda: GoogleIdTokenVerifier(
        CLIENT_ID, jwks_fetcher=fetch_jwks
    )
    for limiter in (auth_api.google_failures, auth_api.admin_failures):
        for key in list(limiter._failures):
            limiter.reset(key)
    gateway_app.cookies.clear()
    yield gateway_app
    gateway_app.cookies.clear()
    app.dependency_overrides.clear()
    app_state.room_history = None


def sign_in(client, token=None):
    return client.post("/api/auth/google", json={"credential": token or google_token()})


# ── Google sign-in ─────────────────────────────────────────────────────────


def test_google_sign_in_creates_cookie_session_and_me_reads_it(client):
    res = sign_in(client)
    assert res.status_code == 200, res.text
    user = res.json()["user"]
    assert user["email"] == "huy@example.com"
    assert user["name"] == "Nguyen Gia Huy"
    assert user["avatar_url"].startswith("https://")
    assert user["id"].startswith("usr_")

    set_cookie = res.headers["set-cookie"]
    assert f"{USER_COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie and "Path=/" in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"user": user}


def test_same_google_account_keeps_its_user_id(client):
    first = sign_in(client).json()["user"]["id"]
    second = sign_in(client, google_token(email="new@example.com")).json()["user"]["id"]
    assert first == second


def test_me_without_session_is_auth_required(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "auth_required"


def test_logout_ends_the_session(client):
    sign_in(client)
    token = client.cookies.get(USER_COOKIE)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json()["error"]["code"] == "auth_required"
    # The old cookie value no longer works anywhere.
    client.cookies.set(USER_COOKIE, token)
    assert client.get("/api/auth/me").json()["error"]["code"] == "session_expired"
    assert client.post("/api/auth/logout").status_code == 204  # idempotent


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: google_token(aud="someone-else.apps.googleusercontent.com"), id="wrong_audience"),
        pytest.param(lambda: google_token(iss="https://evil.example.com"), id="wrong_issuer"),
        pytest.param(lambda: google_token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: google_token(email_verified=False), id="unverified_email"),
        pytest.param(lambda: google_token(private_pem=OTHER_PRIVATE_PEM), id="forged_signature"),
        pytest.param(lambda: google_token(kid="unknown"), id="unknown_key"),
        pytest.param(lambda: "not-a-jwt", id="malformed"),
    ],
)
def test_invalid_google_credentials_are_rejected(client, token):
    res = sign_in(client, token())
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_google_credential"
    assert USER_COOKIE not in res.headers.get("set-cookie", "")


def test_domain_allow_list(client, fake_settings):
    async def fetch_jwks():
        return JWKS, 3600

    app.dependency_overrides[auth_api.get_google_verifier] = lambda: GoogleIdTokenVerifier(
        CLIENT_ID, allowed_domains=["meetqapp.com"], jwks_fetcher=fetch_jwks
    )
    res = sign_in(client)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "account_not_allowed"
    assert sign_in(client, google_token(email="huy@meetqapp.com")).status_code == 200


def test_google_sign_in_unavailable_without_client_id(gateway_app, fake_settings):
    fake_settings.google_client_id = None
    res = gateway_app.post("/api/auth/google", json={"credential": google_token()})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "auth_unavailable"


def test_credential_is_never_logged(client, caplog):
    token = google_token(aud="wrong")
    with caplog.at_level(logging.DEBUG):
        sign_in(client, token)
        sign_in(client)
    assert token not in caplog.text
    assert client.cookies.get(USER_COOKIE) not in caplog.text


def test_session_token_is_stored_hashed(client, fake_redis):
    sign_in(client)
    token = client.cookies.get(USER_COOKIE)
    assert token and not any(token in key for key in fake_redis.data)


def test_user_profile_is_upserted(client):
    user = sign_in(client).json()["user"]
    stored = app_state.room_history.db["users"].docs
    assert len(stored) == 1 and stored[0]["_id"] == user["id"] and stored[0]["google_sub"] == "1098765432"


# ── Protected user endpoints ───────────────────────────────────────────────


def test_room_endpoints_require_a_signed_in_user(client):
    res = client.post("/api/rooms", json={"room_languages": ["vi", "ja"]})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "auth_required"
    assert client.post("/api/test/mic").status_code == 401

    sign_in(client)
    created = client.post("/api/rooms", json={"room_languages": ["vi", "ja"]})
    assert created.status_code == 200, created.text
    room_id = created.json()["room"]["room_id"]
    assert client.get(f"/api/rooms/{room_id}").status_code == 200


def test_room_endpoints_open_when_user_auth_is_off(client, fake_settings):
    fake_settings.user_auth_required = False
    assert client.post("/api/rooms", json={"room_languages": ["vi"]}).status_code == 200


# ── Admin realm ────────────────────────────────────────────────────────────


def admin_sign_in(client, username="ops", password="correct horse battery"):
    return client.post("/api/admin/auth/login", json={"username": username, "password": password})


def test_admin_sign_in_me_logout(client):
    res = admin_sign_in(client)
    assert res.status_code == 200, res.text
    assert res.json()["admin"]["username"] == "ops"
    set_cookie = res.headers["set-cookie"]
    assert f"{ADMIN_COOKIE}=" in set_cookie and "Path=/api/admin" in set_cookie and "SameSite=strict" in set_cookie
    assert client.get("/api/admin/auth/me").status_code == 200
    assert client.post("/api/admin/auth/logout").status_code == 204
    assert client.get("/api/admin/auth/me").json()["error"]["code"] == "admin_auth_required"


@pytest.mark.parametrize("username,password", [("ops", "wrong"), ("someone", "correct horse battery")])
def test_admin_wrong_credentials_share_one_error(client, username, password):
    res = admin_sign_in(client, username, password)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"


def test_admin_login_is_rate_limited(client):
    for _ in range(10):
        admin_sign_in(client, password="wrong")
    res = admin_sign_in(client)
    assert res.status_code == 429


def test_admin_password_hash(client, fake_settings):
    encoded = hash_password("a long admin passphrase")
    assert verify_password("a long admin passphrase", encoded)
    assert not verify_password("A long admin passphrase", encoded)
    fake_settings.admin_password = None
    fake_settings.admin_password_hash = encoded
    try:
        assert admin_sign_in(client, password="a long admin passphrase").status_code == 200
        assert admin_sign_in(client, password="correct horse battery").status_code == 401
    finally:
        fake_settings.admin_password_hash = None


def test_user_and_admin_sessions_are_independent(client):
    sign_in(client)
    # A Google user has no admin access.
    assert client.get("/api/admin/rooms").json()["error"]["code"] == "admin_auth_required"
    assert client.get("/api/admin/auth/me").status_code == 401

    admin_sign_in(client)
    assert client.get("/api/admin/auth/me").status_code == 200
    # Signing the user out leaves the admin session alone, and vice versa.
    client.post("/api/auth/logout")
    assert client.get("/api/admin/auth/me").status_code == 200
    sign_in(client)
    client.post("/api/admin/auth/logout")
    assert client.get("/api/auth/me").status_code == 200


def test_admin_cookie_does_not_authenticate_a_user(client):
    admin_sign_in(client)
    assert client.get("/api/auth/me").json()["error"]["code"] == "auth_required"


# ── CSRF / CORS ────────────────────────────────────────────────────────────


def test_untrusted_origin_cannot_post(client):
    sign_in(client)
    res = client.post("/api/auth/logout", headers={"Origin": "https://evil.example.com"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "origin_not_allowed"
    assert client.get("/api/auth/me").status_code == 200  # still signed in
    assert client.post("/api/auth/logout", headers={"Origin": TRUSTED_ORIGIN}).status_code == 204


def test_credentialed_cors_for_trusted_origin(client):
    res = client.options(
        "/api/auth/google",
        headers={
            "Origin": TRUSTED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.headers["access-control-allow-origin"] == TRUSTED_ORIGIN
    assert res.headers["access-control-allow-credentials"] == "true"
