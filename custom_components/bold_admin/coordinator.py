"""Keeps the Bold refresh-token chain warm."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoldConnectionError, BoldTokenError, async_refresh_token
from .const import (
    CONF_CLIENT_SECRET,
    CONF_ISSUED_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    REFRESH_INTERVAL,
    RETRY_INTERVAL,
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
        age = self._token_age()

        try:
            tokens = await async_refresh_token(
                session,
                entry.data[CONF_REFRESH_TOKEN],
                entry.data[CONF_CLIENT_SECRET],
            )
        except BoldConnectionError as err:
            # The token is probably fine. Keep trying, and sooner than usual,
            # because a chain that stops being refreshed dies of disuse.
            self.update_interval = RETRY_INTERVAL
            raise UpdateFailed(f"Couldn't refresh the Bold token: {err}") from err
        except BoldTokenError as err:
            # A dead chain cannot be recovered automatically. Raise as auth
            # failure so HA starts the reauth flow (a fresh browser login) and
            # shows a repair, instead of failing quietly.
            raise ConfigEntryAuthFailed(
                f"Bold refused a refresh token issued {age} ago, log in again: {err}"
            ) from err
        self.update_interval = REFRESH_INTERVAL

        # Persist immediately. The token we just spent is already dead, so a
        # crash between here and the next run would strand the chain.
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **tokens}
        )
        _LOGGER.info(
            "Bold token rotated, the spent one was issued %s ago; next in %s",
            age,
            REFRESH_INTERVAL,
        )
        return tokens

    def _token_age(self) -> str:
        """Return how long ago the stored refresh token was issued.

        This is the number to read when the chain dies: it bounds how long Bold
        lets a refresh token sit unused.
        """
        if (issued_at := self.config_entry.data.get(CONF_ISSUED_AT)) is None:
            return "an unknown time"
        minutes = round((time.time() - issued_at) / 60)
        return f"{minutes} min"
