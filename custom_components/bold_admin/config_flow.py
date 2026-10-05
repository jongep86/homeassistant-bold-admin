"""Config flow for Bold Admin.

Logging in: Home Assistant shows the Bold login link, the user logs in, and
pastes back the `com.boldsmartlock://auth?code=...` URL the browser couldn't
open. The same flow handles reauth when the refresh chain has died.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import secrets
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BoldConnectionError,
    BoldTokenError,
    async_exchange_code,
    async_refresh_token,
    authorize_url,
    generate_pkce,
    parse_redirect,
)
from .const import CONF_ACCOUNT_ID, CONF_CLIENT_SECRET, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_REDIRECT_URL = "redirect_url"


class BoldAdminConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to Bold with the app's own client, for a full-scope token."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._state = secrets.token_urlsafe(16)
        self._code_verifier, self._code_challenge = generate_pkce()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to log in."""
        return self.async_show_menu(step_id="user", menu_options=["login", "token"])

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Log in again after Bold refused the refresh token."""
        return await self.async_step_user()

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange the code from the pasted redirect for tokens."""
        errors: dict[str, str] = {}
        reauth = self.source == SOURCE_REAUTH
        known_secret = (
            self._get_reauth_entry().data[CONF_CLIENT_SECRET] if reauth else None
        )

        if user_input is not None:
            client_secret = known_secret or user_input[CONF_CLIENT_SECRET]
            try:
                code, state = parse_redirect(user_input[CONF_REDIRECT_URL])
            except ValueError:
                errors[CONF_REDIRECT_URL] = "no_code"
            else:
                if state is not None and state != self._state:
                    # A redirect from an earlier attempt; its code belongs to
                    # another PKCE challenge.
                    errors[CONF_REDIRECT_URL] = "wrong_state"
                else:
                    try:
                        tokens = await async_exchange_code(
                            async_get_clientsession(self.hass),
                            code,
                            self._code_verifier,
                            client_secret,
                        )
                    except BoldConnectionError as err:
                        _LOGGER.debug("Bold code exchange failed: %s", err)
                        errors["base"] = "cannot_connect"
                    except BoldTokenError as err:
                        _LOGGER.debug("Bold refused the code: %s", err)
                        errors["base"] = "invalid_code"
                    else:
                        return await self._async_finish(tokens, client_secret)

        schema = {vol.Required(CONF_REDIRECT_URL): str}
        if not reauth:
            schema = {vol.Required(CONF_CLIENT_SECRET): str, **schema}
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "url": authorize_url(self._state, self._code_challenge)
            },
            errors=errors,
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fall back to a hand-captured refresh token, spent to validate it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                tokens = await async_refresh_token(
                    async_get_clientsession(self.hass),
                    user_input[CONF_REFRESH_TOKEN],
                    user_input[CONF_CLIENT_SECRET],
                )
            except BoldConnectionError as err:
                _LOGGER.debug("Bold token validation failed: %s", err)
                errors["base"] = "cannot_connect"
            except BoldTokenError as err:
                _LOGGER.debug("Bold refused the token: %s", err)
                errors["base"] = "invalid_auth"
            else:
                # Validation rotated the chain, so store what came back rather
                # than what was typed in. The submitted token is already dead.
                return await self._async_finish(
                    tokens, user_input[CONF_CLIENT_SECRET]
                )

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REFRESH_TOKEN): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                }
            ),
            errors=errors,
        )

    async def _async_finish(
        self, tokens: dict[str, Any], client_secret: str
    ) -> ConfigFlowResult:
        """Create the entry, or update it when reauthenticating."""
        data = {CONF_CLIENT_SECRET: client_secret, **tokens}
        await self.async_set_unique_id(str(tokens[CONF_ACCOUNT_ID]))
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Bold account {tokens[CONF_ACCOUNT_ID]}", data=data
        )
