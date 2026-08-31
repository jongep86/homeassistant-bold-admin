"""Config flow for Bold Admin."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BoldTokenError, async_refresh_token
from .const import CONF_ACCOUNT_ID, CONF_CLIENT_SECRET, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): str,
        vol.Required(CONF_CLIENT_SECRET): str,
    }
)


class BoldAdminConfigFlow(ConfigFlow, domain=DOMAIN):
    """Bootstrap the chain once, from a hand-captured refresh token."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the supplied token by actually spending it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                tokens = await async_refresh_token(
                    session,
                    user_input[CONF_REFRESH_TOKEN],
                    user_input[CONF_CLIENT_SECRET],
                )
            except BoldTokenError as err:
                _LOGGER.debug("Bold token validation failed: %s", err)
                errors["base"] = "invalid_auth"
            else:
                # Validation rotated the chain, so store what came back rather
                # than what was typed in. The submitted token is already dead.
                await self.async_set_unique_id(str(tokens[CONF_ACCOUNT_ID]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Bold account {tokens[CONF_ACCOUNT_ID]}",
                    data={
                        CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                        **tokens,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
