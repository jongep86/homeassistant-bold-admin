"""Minimal Bold OAuth2 client: the authorization-code and refresh grants.

The only client credentials we hold (`BoldApp`) are registered against the
app's custom scheme `com.boldsmartlock://auth`, so Home Assistant can't receive
the redirect itself. The login flow has the user paste the redirect URL that
their browser failed to open, and exchanges the code in it here.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from aiohttp import ClientError, ClientSession

from .const import (
    AUTHORIZE_URL,
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    OAUTH_TOKEN_URL,
    REDIRECT_URI,
    SCOPE,
)


class BoldTokenError(Exception):
    """Bold refused to issue a token. The chain or code is dead."""


class BoldConnectionError(Exception):
    """Bold couldn't be reached, or failed on its side. Worth retrying."""


def generate_pkce() -> tuple[str, str]:
    """Return a PKCE code verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(state: str, code_challenge: str) -> str:
    """Return the Bold login URL, as the app opens it."""
    return f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "nonce": secrets.token_urlsafe(16),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )


def parse_redirect(pasted: str) -> tuple[str, str | None]:
    """Return the code, and the state if present, from a pasted redirect.

    Accepts the full `com.boldsmartlock://auth?code=...&state=...` URL, or just
    the code.
    """
    pasted = pasted.strip()
    if "code=" not in pasted:
        if not pasted or any(char in pasted for char in "?&= "):
            raise ValueError("no code in pasted text")
        return pasted, None
    query = parse_qs(urlsplit(pasted).query or pasted.split("?", 1)[-1])
    if not (code := query.get("code", [""])[0]):
        raise ValueError("no code in pasted text")
    return code, query.get("state", [None])[0]


async def async_exchange_code(
    session: ClientSession, code: str, code_verifier: str, client_secret: str
) -> dict[str, Any]:
    """Exchange an authorization code for a fresh token pair."""
    return await _async_token_request(
        session,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
            "client_id": CLIENT_ID,
            "client_secret": client_secret,
        },
    )


async def async_refresh_token(
    session: ClientSession, refresh_token: str, client_secret: str
) -> dict[str, Any]:
    """Exchange a refresh token for a fresh token pair.

    Bold rotates the refresh token on every call and the old value stops
    working immediately, so the caller MUST persist what comes back.
    """
    return await _async_token_request(
        session,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )


async def _async_token_request(
    session: ClientSession, data: dict[str, str]
) -> dict[str, Any]:
    try:
        response = await session.post(OAUTH_TOKEN_URL, data=data)
        body = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        # Not a verdict on the token: the request may never have reached Bold.
        # Treating this as an auth failure stops the keep-alive, and a healthy
        # chain then dies of disuse.
        raise BoldConnectionError(f"network error talking to Bold: {err}") from err

    if response.status >= 500 or response.status == 429:
        raise BoldConnectionError(f"HTTP {response.status}: {body}")
    if response.status != 200:
        # 400 invalid_grant: the chain expired, or the code was already used.
        raise BoldTokenError(f"HTTP {response.status}: {body}")

    try:
        return {
            CONF_ACCESS_TOKEN: body[CONF_ACCESS_TOKEN],
            CONF_REFRESH_TOKEN: body[CONF_REFRESH_TOKEN],
            CONF_ACCOUNT_ID: body.get(CONF_ACCOUNT_ID),
            CONF_EXPIRES_AT: time.time() + body.get("expires_in", 86400),
        }
    except (KeyError, TypeError) as err:
        raise BoldTokenError(f"unexpected token response shape: {body}") from err
