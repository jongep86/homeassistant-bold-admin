# CLAUDE.md — homeassistant-bold-admin

Single-purpose Home Assistant custom integration (`custom_components/bold_admin`): keeps a **write-capable** Bold Smart Lock token (scope `manage`) alive. It owns no locks and never touches the stock `bold` integration — see README.md for the full rationale.

## How it works

A `DataUpdateCoordinator` spends the refresh token every 6 hours and persists the rotated replacement back into the config entry. Bold rotates the refresh token on every use and kills an unused chain after ~11–21 days idle; the coordinator's cadence is the whole point of this integration.

## Hard rules

- **Never refresh or spend the token by hand** (curl, scripts, REPL). One manual refresh desyncs the chain stored in HA and the next coordinator cycle dies; recovery is a full browser re-bootstrap.
- Auth state lives in the HA config entry (`bold_admin`), not in files in this repo.
- User/share management on the locks (front-door, loft) goes through `~/bin/bold-ha.sh`, which rides on this integration's token.

## Layout

HACS-style repo: `custom_components/bold_admin/` (coordinator, api, config_flow, sensor) + `hacs.json`. Deploy = copy/pull into the HA server's `/config/custom_components/` and restart HA.
