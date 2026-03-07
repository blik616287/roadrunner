import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from .db import get_pool
from .services import working_memory


_settings_ref = None


def set_settings(settings):
    global _settings_ref
    _settings_ref = settings


def _get_settings():
    assert _settings_ref is not None, "Auth settings not initialized"
    return _settings_ref


def _redis():
    return working_memory.get_client()


# ── Session management (Redis-backed) ────────────────────────────────

async def create_session(user_id: str, email: str, name: str | None, picture: str | None) -> str:
    token = secrets.token_urlsafe(48)
    settings = _get_settings()
    data = json.dumps({"id": user_id, "email": email, "name": name, "picture": picture})
    await _redis().setex(f"auth:session:{token}", settings.auth_session_ttl_seconds, data)
    return token


async def get_session(token: str) -> dict | None:
    data = await _redis().get(f"auth:session:{token}")
    if data is None:
        return None
    return json.loads(data)


async def delete_session(token: str):
    await _redis().delete(f"auth:session:{token}")


# ── API key helpers ───────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (raw_key, sha256_hash, prefix)."""
    raw = "grk_" + secrets.token_hex(24)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, key_hash, prefix


async def validate_api_key(raw_key: str) -> dict | None:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT k.user_id, u.email, u.name, u.picture
        FROM auth_api_keys k
        JOIN auth_users u ON u.id = k.user_id
        WHERE k.key_hash = $1
          AND k.revoked_at IS NULL
          AND (k.expires_at IS NULL OR k.expires_at > now())
        """,
        key_hash,
    )
    if row is None:
        return None
    return {"id": row["user_id"], "email": row["email"], "name": row["name"], "picture": row["picture"]}


# ── FastAPI dependency ────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    settings = _get_settings()
    if not settings.auth_enabled:
        return {"id": "anonymous", "email": "anonymous@local", "name": "Anonymous", "picture": None}

    # Check session cookie
    token = request.cookies.get("graphrag_session")
    if token:
        session = await get_session(token)
        if session:
            return session

    # Check API key in Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
        if key.startswith("grk_"):
            user = await validate_api_key(key)
            if user:
                return user

    raise HTTPException(status_code=401, detail="Not authenticated")


# ── User management (PostgreSQL) ─────────────────────────────────────

async def upsert_user(email: str, name: str | None, picture: str | None) -> str:
    pool = get_pool()
    row = await pool.fetchrow("SELECT id FROM auth_users WHERE email = $1", email)
    if row:
        user_id = row["id"]
        await pool.execute(
            "UPDATE auth_users SET name = $1, picture = $2, last_login_at = now() WHERE id = $3",
            name, picture, user_id,
        )
    else:
        user_id = str(uuid.uuid4())
        await pool.execute(
            "INSERT INTO auth_users (id, email, name, picture, last_login_at) VALUES ($1, $2, $3, $4, now())",
            user_id, email, name, picture,
        )
    return user_id


async def create_api_key_record(user_id: str, name: str, rotation_days: int | None) -> tuple[str, dict]:
    """Create an API key record. Returns (raw_key, record_dict)."""
    raw_key, key_hash, prefix = generate_api_key()
    key_id = str(uuid.uuid4())
    expires_at = None
    if rotation_days and rotation_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=rotation_days)

    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO auth_api_keys (id, user_id, name, key_hash, key_prefix, rotation_days, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        key_id, user_id, name, key_hash, prefix, rotation_days, expires_at,
    )
    return raw_key, {
        "id": key_id,
        "name": name,
        "key_prefix": prefix,
        "rotation_days": rotation_days,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def list_api_keys(user_id: str) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, key_prefix, rotation_days, expires_at, created_at, revoked_at
        FROM auth_api_keys
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "key_prefix": row["key_prefix"],
            "rotation_days": row["rotation_days"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "created_at": row["created_at"].isoformat(),
            "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
        }
        for row in rows
    ]


async def revoke_api_key(key_id: str, user_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        "UPDATE auth_api_keys SET revoked_at = now() WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL",
        key_id, user_id,
    )
    return result == "UPDATE 1"
