"""Constants for the Bold Admin integration."""

from datetime import timedelta

DOMAIN = "bold_admin"

API_URL = "https://api.boldsmartlock.com"
OAUTH_TOKEN_URL = f"{API_URL}/v2/oauth/token"

# The Bold mobile app's own OAuth client. Unlike the Nabu Casa client used by
# the stock `bold` integration, a token minted through this one carries the
# full scope set (read manage activate events settings authorize), which is
# what share/user management requires.
CLIENT_ID = "BoldApp"

CONF_ACCESS_TOKEN = "access_token"
CONF_ACCOUNT_ID = "account_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_EXPIRES_AT = "expires_at"
CONF_REFRESH_TOKEN = "refresh_token"

# Bold expires a refresh token that goes unused. Observed death window is
# 11 to 21 days idle (see docs). Six hours leaves a very wide margin while
# staying far below the 24h access-token lifetime, so the stored access token
# is essentially always usable by an external caller.
REFRESH_INTERVAL = timedelta(hours=6)
