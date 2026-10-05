"""Tests for Bold Admin: login, reauth and keeping the chain alive."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold_admin.api import parse_redirect
from custom_components.bold_admin.const import (
    DOMAIN,
    OAUTH_TOKEN_URL,
    REFRESH_INTERVAL,
    RETRY_INTERVAL,
)

TOKENS = {
    "access_token": "access-2",
    "refresh_token": "refresh-2",
    "token_type": "Bearer",
    "expires_in": 86400,
    "account_id": 7744,
}


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="7744",
        title="Bold account 7744",
        data={
            "client_secret": "secret",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "account_id": 7744,
            "expires_at": 0,
        },
    )
    entry.add_to_hass(hass)
    return entry


def _form_url(result: dict) -> str:
    return result["description_placeholders"]["url"]


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        ("com.boldsmartlock://auth?code=abc&state=xyz", ("abc", "xyz")),
        ("  com.boldsmartlock://auth?state=xyz&code=abc  ", ("abc", "xyz")),
        ("abc123", ("abc123", None)),
    ],
)
def test_parse_redirect(pasted: str, expected: tuple) -> None:
    """Test the code is found in a pasted redirect, or taken as is."""
    assert parse_redirect(pasted) == expected


@pytest.mark.parametrize("pasted", ["", "com.boldsmartlock://auth?state=x", "a b"])
def test_parse_redirect_without_code(pasted: str) -> None:
    """Test text without a code is rejected."""
    with pytest.raises(ValueError):
        parse_redirect(pasted)


async def test_login(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Test logging in with a pasted redirect creates the entry."""
    aioclient_mock.post(OAUTH_TOKEN_URL, json=TOKENS)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    query = parse_qs(urlsplit(_form_url(result)).query)
    assert query["client_id"] == ["BoldApp"]
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "client_secret": "secret",
            "redirect_url": f"com.boldsmartlock://auth?code=the-code&state={state}",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["refresh_token"] == "refresh-2"
    assert result["data"]["client_secret"] == "secret"
    assert result["result"].unique_id == "7744"

    sent = aioclient_mock.mock_calls[0][2]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["redirect_uri"] == "com.boldsmartlock://auth"
    assert sent["code_verifier"]


async def test_login_wrong_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a redirect from another login attempt is rejected unspent."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "client_secret": "secret",
            "redirect_url": "com.boldsmartlock://auth?code=c&state=other",
        },
    )
    assert result["errors"] == {"redirect_url": "wrong_state"}
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("status", "error"), [(400, "invalid_code"), (503, "cannot_connect")]
)
async def test_login_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int, error: str
) -> None:
    """Test Bold refusing the code, or failing, is shown on the form."""
    aioclient_mock.post(OAUTH_TOKEN_URL, status=status, json={"error": "x"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"client_secret": "secret", "redirect_url": "the-code"}
    )
    assert result["errors"] == {"base": error}


async def test_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Test logging in again updates the entry, reusing the client secret."""
    entry = _entry(hass)
    aioclient_mock.post(OAUTH_TOKEN_URL, json=TOKENS)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    assert "client_secret" not in result["data_schema"].schema
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"redirect_url": "the-code"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["refresh_token"] == "refresh-2"
    assert entry.data["client_secret"] == "secret"

    # The entry is reloaded with the new tokens; unload it so its refresh timer
    # doesn't outlive the test.
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_wrong_account(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test logging in to another Bold account doesn't replace the entry."""
    entry = _entry(hass)
    aioclient_mock.post(OAUTH_TOKEN_URL, json={**TOKENS, "account_id": 1})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"redirect_url": "the-code"}
    )
    assert result["reason"] == "wrong_account"
    assert entry.data["refresh_token"] == "refresh-1"


async def test_refresh_persists_rotated_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test setup spends the refresh token and stores the replacement."""
    entry = _entry(hass)
    aioclient_mock.post(OAUTH_TOKEN_URL, json=TOKENS)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["refresh_token"] == "refresh-2"
    assert entry.data["access_token"] == "access-2"
    assert entry.runtime_data.update_interval == REFRESH_INTERVAL


async def test_network_error_retries_sooner(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a network failure is retried, not treated as a dead chain."""
    entry = _entry(hass)
    aioclient_mock.post(OAUTH_TOKEN_URL, json=TOKENS)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.post(OAUTH_TOKEN_URL, exc=TimeoutError())
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == RETRY_INTERVAL
    assert not list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))
    assert entry.data["refresh_token"] == "refresh-2"

    aioclient_mock.clear_requests()
    aioclient_mock.post(OAUTH_TOKEN_URL, json={**TOKENS, "refresh_token": "refresh-3"})
    await coordinator.async_refresh()
    assert coordinator.update_interval == REFRESH_INTERVAL
    assert entry.data["refresh_token"] == "refresh-3"


async def test_refused_token_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test Bold refusing the refresh token starts the reauth flow."""
    entry = _entry(hass)
    aioclient_mock.post(
        OAUTH_TOKEN_URL,
        status=400,
        json={"error": "invalid_grant", "error_description": "InvalidRefreshToken"},
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))
    assert flows and flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH


async def test_retry_interval_is_shorter() -> None:
    """Test a failed refresh is retried well within the regular cadence."""
    assert RETRY_INTERVAL < REFRESH_INTERVAL / 4
    assert timedelta(0) < RETRY_INTERVAL
