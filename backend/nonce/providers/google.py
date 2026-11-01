"""Google API access with a user's stored refresh token, shared by Gmail, Calendar and Drive."""

import json

from ..config import settings
from ..crypto import decrypt

SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar": "https://www.googleapis.com/auth/calendar.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
}


def service(credentials_enc: str, provider: str, api: str, version: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    info = json.loads(decrypt(credentials_enc))
    s = settings()
    creds = Credentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=[SCOPES[provider]],
    )
    return build(api, version, credentials=creds, cache_discovery=False)
