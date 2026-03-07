import base64
import hashlib
import json
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..auth import (
    _get_settings,
    get_current_user,
    get_session,
    create_session,
    delete_session,
    upsert_user,
    create_api_key_record,
    list_api_keys,
    revoke_api_key,
)
from ..services import working_memory

logger = logging.getLogger("orchestrator.auth")
router = APIRouter(tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _redis():
    return working_memory.get_client()


# ── OIDC endpoints ────────────────────────────────────────────────────

@router.get("/auth/login")
async def auth_login():
    settings = _get_settings()
    if not settings.auth_enabled:
        raise HTTPException(404, "Authentication is not enabled")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge_b64 = base64.urlsafe_b64encode(code_challenge_bytes).rstrip(b"=").decode()

    # Store state + verifier in Redis (10 min TTL)
    await _redis().setex(
        f"auth:oidc_state:{state}",
        600,
        json.dumps({"code_verifier": code_verifier}),
    )

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.auth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/auth/callback")
async def auth_callback(code: str, state: str):
    settings = _get_settings()
    if not settings.auth_enabled:
        raise HTTPException(404, "Authentication is not enabled")

    # Validate state
    state_data = await _redis().get(f"auth:oidc_state:{state}")
    if state_data is None:
        raise HTTPException(400, "Invalid or expired state parameter")
    await _redis().delete(f"auth:oidc_state:{state}")
    state_obj = json.loads(state_data)
    code_verifier = state_obj["code_verifier"]

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": settings.auth_redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.error(f"Token exchange failed: {token_resp.text}")
            raise HTTPException(502, "Failed to exchange authorization code")
        tokens = token_resp.json()

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            logger.error(f"Userinfo fetch failed: {userinfo_resp.text}")
            raise HTTPException(502, "Failed to fetch user information")
        userinfo = userinfo_resp.json()

    email = userinfo.get("email", "")
    name = userinfo.get("name")
    picture = userinfo.get("picture")

    if not email:
        raise HTTPException(400, "No email returned from Google")

    # Check domain restriction
    if settings.auth_allowed_domain:
        domain = email.split("@")[-1]
        if domain != settings.auth_allowed_domain:
            raise HTTPException(403, f"Email domain '{domain}' is not allowed")

    # Upsert user and create session
    user_id = await upsert_user(email, name, picture)
    token = await create_session(user_id, email, name, picture)

    # Set cookie and redirect to frontend
    response = RedirectResponse(url="/", status_code=302)
    secure = settings.auth_redirect_uri.startswith("https://")
    response.set_cookie(
        key="graphrag_session",
        value=token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    return response


@router.post("/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get("graphrag_session")
    if token:
        await delete_session(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("graphrag_session", path="/")
    return response


# ── User info ─────────────────────────────────────────────────────────

@router.get("/auth/me")
async def auth_me(request: Request):
    settings = _get_settings()
    if not settings.auth_enabled:
        return {"email": "anonymous@local", "name": "Anonymous", "picture": None, "auth_enabled": False}

    # Check session
    token = request.cookies.get("graphrag_session")
    if token:
        session = await get_session(token)
        if session:
            return {**session, "auth_enabled": True}

    raise HTTPException(401, "Not authenticated")


# ── API key management ────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    name: str
    rotation_days: int | None = None


@router.get("/auth/api-keys")
async def get_api_keys(user: dict = Depends(get_current_user)):
    keys = await list_api_keys(user["id"])
    return {"keys": keys}


@router.post("/auth/api-keys")
async def create_api_key(body: CreateApiKeyRequest, user: dict = Depends(get_current_user)):
    raw_key, record = await create_api_key_record(user["id"], body.name, body.rotation_days)
    return {"raw_key": raw_key, **record}


@router.delete("/auth/api-keys/{key_id}")
async def delete_api_key(key_id: str, user: dict = Depends(get_current_user)):
    revoked = await revoke_api_key(key_id, user["id"])
    if not revoked:
        raise HTTPException(404, "API key not found or already revoked")
    return {"status": "revoked"}
