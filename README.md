# Bold Admin

A Home Assistant integration whose only job is to keep a **write-capable** Bold Smart
Lock token alive.

It owns no locks and exposes no controls. It sits alongside the
[stock `bold` integration](https://github.com/lwestenberg/homeassistant_bold), which it
never touches.

## Why this exists

Managing users and shares on a Bold lock over the API needs a token with the `manage`
scope, and *keeping* one is the hard part.

- **A standalone refresh chain decays.** Bold rotates the refresh token on every use and
  expires one that goes unused. Observed death window: 11 to 21 days idle. When it dies,
  recovery means a full browser re-bootstrap.
- **The stock `bold` integration cannot help.** If it was set up through Home Assistant
  Cloud, Nabu Casa scopes that token for lock control only. Reads succeed, but every
  share mutation returns `403`.
- **Patching the stock integration is worse.** Re-authenticating it onto your own
  credentials disturbs a working integration that your lock entities and dashboards
  depend on, and the patch needs reapplying after every update.

Hence a separate domain.

## How it works

A `DataUpdateCoordinator` spends the refresh token every 6 hours and persists the
rotated replacement back to the config entry.

**That periodic refresh is the entire feature.** Merely storing a token would decay
exactly like a standalone chain does. The stock integration stays healthy only as a side
effect of polling locks every few seconds; this one has to do it deliberately.

Six hours sits far below the observed death window, and below the 24h access-token
lifetime, so the stored access token is essentially always usable by an external caller.

`sensor.bold_admin_token_expires` makes liveness visible. A chain that dies silently can
go unnoticed for weeks, so alert on this if you want a real safety net.

## Install

### HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add this repository's URL, category **Integration**
3. Install **Bold Admin**, then restart Home Assistant

### Manual

Copy `custom_components/bold_admin/` into your `/config/custom_components/` and restart.

## Set up

You need two things: a **refresh token** and the **`BoldApp` client secret**.

Capturing a refresh token is a one-time manual step, because Bold has no automated
initial login. Open the OAuth authorize URL with `client_id=BoldApp`, log in, grab the
`code` from the redirect that fails to open `com.boldsmartlock://auth`, and exchange it
at `POST /v2/oauth/token` with `grant_type=authorization_code`.

Then: Settings → Devices & Services → Add Integration → **Bold Admin**, and paste both
values.

The token you paste is spent immediately to validate it, and the rotated replacement is
what gets stored. That is intentional, it proves the chain works before the entry exists.

## Using the token

Read `access_token` from the config entry in `/config/.storage/core.config_entries` and
present it as a bearer token to `api.boldsmartlock.com`.

### The one rule

**Read `access_token`, never `refresh_token`.**

A bearer token rotates nothing, so the session stays intact. Two holders of one refresh
chain will invalidate each other on the next rotation, and the loser has to re-bootstrap
by hand. For the same reason, never call the refresh grant yourself against a chain this
integration owns.

## Not implemented

Service calls (`invite_user`, `remove_share`) and calendar-driven guest provisioning.
This component is the natural home for both, but neither is needed to solve the auth
problem it exists for.

## Credits

Independent of, and deliberately decoupled from,
[`lwestenberg/homeassistant_bold`](https://github.com/lwestenberg/homeassistant_bold)
and [`lwestenberg/bold_smart_lock`](https://github.com/lwestenberg/bold_smart_lock). No
code is shared: the OAuth client here is about 70 lines implementing only the refresh
grant.

The Bold API is not officially documented for this use. Endpoints were determined by
observing the app's own traffic.
