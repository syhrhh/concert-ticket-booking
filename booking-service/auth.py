"""Staff authentication: PBKDF2 password hashing and HS256 JWT (standard library only)."""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

import config
import db

log = logging.getLogger("booking.auth")

PBKDF2_ITERATIONS = 200_000


# ---- passwords -----------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False  # e.g. the demo users' placeholder hash


# ---- tokens --------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str) -> str:
    return _b64(hmac.new(config.JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())


def create_token(user_id: int, role: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64(json.dumps({"sub": str(user_id), "role": role, "iat": now,
                               "exp": now + config.JWT_TTL_SECONDS}, separators=(",", ":")).encode())
    return f"{header}.{payload}.{_sign(f'{header}.{payload}')}"


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Return the claims, or None if the token is malformed, forged or expired."""
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(f"{header}.{payload}")):
            return None
        if json.loads(_unb64(header)).get("alg") != "HS256":
            return None
        claims = json.loads(_unb64(payload))
        return claims if claims.get("exp", 0) > time.time() else None
    except Exception:
        return None


# ---- admin account -------------------------------------------------------
def ensure_admin() -> None:
    """Create the admin account on first start (idempotent; never overwrites)."""
    with db.pool.connection() as conn:
        row = conn.execute("SELECT user_id, role FROM users WHERE email = %s",
                           (config.ADMIN_EMAIL,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'ADMIN')",
                (config.ADMIN_NAME, config.ADMIN_EMAIL, hash_password(config.ADMIN_PASSWORD)))
            log.info("created admin account %s", config.ADMIN_EMAIL)
        elif row["role"] != "ADMIN":
            conn.execute("UPDATE users SET role = 'ADMIN' WHERE user_id = %s", (row["user_id"],))
    if config.JWT_SECRET == config.DEFAULT_JWT_SECRET:
        log.warning("JWT_SECRET is the development default - set a real secret outside local demos")
