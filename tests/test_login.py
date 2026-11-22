"""Sign-in checks against the running stack:  pytest tests/test_login.py -v"""
import os

import requests

BOOKING = os.getenv("BOOKING_URL", "http://127.0.0.1:5001")
CUSTOMER_PW = os.getenv("DEMO_CUSTOMER_PASSWORD", "customer123")


def login(email, password):
    return requests.post(f"{BOOKING}/api/auth/login", json={"email": email, "password": password}, timeout=10)


def test_demo_customers_can_sign_in_with_role_customer():
    for email, uid in (("user.a@example.com", 1), ("user.b@example.com", 2)):
        r = login(email, CUSTOMER_PW)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["user_id"] == uid and body["user"]["role"] == "CUSTOMER" and body["token"]


def test_admin_signs_in_with_role_admin():
    r = login("admin@encore.local", os.getenv("ADMIN_PASSWORD", "admin123"))
    assert r.status_code == 200 and r.json()["user"]["role"] == "ADMIN"


def test_wrong_password_and_unknown_email_get_the_same_error():
    for creds in (("user.a@example.com", "nope"), ("nobody@example.com", "x")):
        r = login(*creds)
        assert r.status_code == 401 and r.json()["detail"] == "INVALID_CREDENTIALS"


def test_me_requires_a_valid_token_and_returns_the_user():
    token = login("user.b@example.com", CUSTOMER_PW).json()["token"]
    r = requests.get(f"{BOOKING}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200 and r.json()["email"] == "user.b@example.com"
    assert requests.get(f"{BOOKING}/api/auth/me", timeout=10).status_code == 401
    assert requests.get(f"{BOOKING}/api/auth/me", headers={"Authorization": "Bearer x.y.z"}, timeout=10).status_code == 401


def test_customer_token_cannot_use_admin_routes():
    token = login("user.a@example.com", CUSTOMER_PW).json()["token"]
    r = requests.get(f"{BOOKING}/api/admin/stats", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 403 and r.json()["detail"] == "ADMIN_ONLY"


def _register(**body):
    return requests.post(f"{BOOKING}/api/auth/register", json=body, timeout=10)


def test_register_creates_a_customer_who_can_sign_in():
    import uuid
    email = f"new.{uuid.uuid4().hex[:8]}@example.com"
    r = _register(name="New Customer", email=email.upper(), password="longenough1")  # e-mail is case-insensitive
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "CUSTOMER" and r.json()["user"]["email"] == email
    assert login(email, "longenough1").json()["user"]["role"] == "CUSTOMER"
    assert _register(name="Again", email=email, password="longenough1").json()["detail"] == "EMAIL_TAKEN"


def test_register_cannot_create_staff_or_take_the_admin_email():
    r = _register(name="Sneaky", email="sneaky@example.com", password="longenough1", role="ADMIN")
    assert r.status_code == 422  # unknown field `role` is rejected
    r = _register(name="Sneaky", email="admin@encore.local", password="longenough1")
    assert r.status_code == 409 and r.json()["detail"] == "EMAIL_TAKEN"


def test_register_validates_input():
    assert _register(name="X", email="not-an-email", password="longenough1").status_code == 422
    assert _register(name="X", email="x@example.com", password="short").status_code == 422
    assert _register(name="   ", email="x@example.com", password="longenough1").status_code == 422
