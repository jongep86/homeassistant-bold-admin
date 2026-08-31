"""Minimal Bold OAuth2 client. Refresh grant only.

Deliberately does not implement the authorization-code flow: that one needs a
redirect_uri, and the only client credentials we hold (`BoldApp`) are
registered against the app's custom scheme `com.boldsmartlock://auth`. Whether
Bold would accept a different redirect_uri is untested and irrelevant here,
because the refresh grant never sends one. Bootstrap happens once by hand
(see README), and this module keeps it alive forever after.
"""

from __future__ import annotations

import time
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    OAUTH_TOKEN_URL,
)


class BoldTokenError(Exception):
    """The token endpoint refused to issue a token."""


async def async_refresh_token(
    session: ClientSession, refresh_token: str, client_secret: str
) -> dict[str, Any]:
    """Exchange a refresh token for a fresh token pair.

    Bold rotates the refresh token on every call and the old value stops
    working immediately, so the caller MUST persist what comes back. Losing a
    returned refresh token means re-bootstrapping through the browser login.
    """
    try:
        response = await session.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
        body = await response.json(content_type=None)
    except ClientError as err:
        raise BoldTokenError(f"network error talking to Bold: {err}") from err

    if response.status != 200:
        # 400 here almost always means the chain expired from disuse, which is
        # exactly the failure this integration exists to prevent.
        raise BoldTokenError(f"HTTP {response.status}: {body}")

    try:
        return {
            CONF_ACCESS_TOKEN: body[CONF_ACCESS_TOKEN],
            CONF_REFRESH_TOKEN: body[CONF_REFRESH_TOKEN],
            CONF_ACCOUNT_ID: body.get(CONF_ACCOUNT_ID),
            CONF_EXPIRES_AT: time.time() + body.get("expires_in", 86400),
        }
    except KeyError as err:
        raise BoldTokenError(f"unexpected token response shape: {body}") from err
