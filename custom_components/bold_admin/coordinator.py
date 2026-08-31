"""Keeps the Bold refresh-token chain warm."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import BoldTokenError, async_refresh_token
from .const import (
    CONF_CLIENT_SECRET,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class BoldAdminCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Spend the refresh token on a schedule so the chain never goes idle.

    This periodic refresh IS the feature, not incidental plumbing. Merely
    storing a refresh token is not enough: Bold expires unused ones, which is
    how the previous standalone chain died. The stock `bold` integration stays
    healthy only as a side effect of polling the locks every few seconds.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=REFRESH_INTERVAL,
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Rotate the token and persist the new one."""
        entry = self.config_entry
        session = async_get_clientsession(self.hass)

        try:
            tokens = await async_refresh_token(
                session,
                entry.data[CONF_REFRESH_TOKEN],
                entry.data[CONF_CLIENT_SECRET],
            )
        except BoldTokenError as err:
            # A dead chain cannot be recovered automatically, re-bootstrapping
            # needs a browser login. Raise as auth failure so HA shows a repair
            # notification instead of failing quietly, which is precisely how
            # the last expiry went unnoticed for three weeks.
            raise ConfigEntryAuthFailed(
                f"Bold refused the refresh token, re-bootstrap needed: {err}"
            ) from err

        # Persist immediately. The token we just spent is already dead, so a
        # crash between here and the next run would strand the chain.
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **tokens}
        )
        _LOGGER.debug("Bold token rotated, next refresh in %s", REFRESH_INTERVAL)
        return tokens
