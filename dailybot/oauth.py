"""Google OAuth handler.

Reads ~/.config/dailybot/credentials.json (downloaded by the user from
Google Cloud Console), runs InstalledAppFlow on first use, caches the
result in ~/.config/dailybot/token.json with mode 0600, refreshes
automatically on expiry.

The two tool modules (calendar.py, gmail.py) call `get_service(...)` to
get an authenticated API client. If credentials.json is missing they get
a clear error pointing at `make google-setup`."""
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


CONFIG_DIR = Path.home() / ".config" / "dailybot"
CREDS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"

# Smallest scopes that cover the tools we ship. No gmail.send -- bot can
# only draft replies, never send them.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


class MissingCredentialsError(RuntimeError):
    """Raised when ~/.config/dailybot/credentials.json doesn't exist."""


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except Exception:
        pass


def _load_cached() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception:
        return None


def _save(creds: Credentials) -> None:
    _ensure_dir()
    TOKEN_PATH.write_text(creds.to_json())
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except Exception:
        pass


def get_credentials(interactive: bool = False) -> Credentials:
    """Return refreshed Credentials, or raise MissingCredentialsError if the
    user hasn't run `make google-setup` yet.

    Args:
        interactive: if True, open a browser to complete the OAuth flow on
            first use. Tool calls pass False so we never block on a flow
            mid-conversation -- the bot just gets a clear error.
    """
    creds = _load_cached()

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception:
            pass  # fall through to fresh flow if refresh fails

    if not interactive:
        raise MissingCredentialsError(
            "No valid Google credentials. Run `make google-setup` to set up "
            "Calendar + Gmail (one-time)."
        )

    if not CREDS_PATH.exists():
        raise MissingCredentialsError(
            f"Missing {CREDS_PATH}. Run `make google-setup` for the one-time "
            "setup instructions."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save(creds)
    return creds


def get_service(api: str, version: str):
    """Build an authenticated googleapiclient. Raises MissingCredentialsError
    if the user hasn't run `make google-setup`."""
    creds = get_credentials(interactive=False)
    return build(api, version, credentials=creds, cache_discovery=False)
