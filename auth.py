"""OAuth 2.0 handling for the Photos Picker + YouTube Data APIs.

Runs the installed-app consent flow once and caches a refresh token in
token.json so later runs don't need a browser.
"""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

# photoslibrary.readonly.appcreateddata is NOT requested: this tool never
# creates media items, and the Picker API's own readonly scope is all that's
# needed to read items the user selects in a picker session.
SCOPES = [
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    # youtube.upload alone doesn't cover videos.list(status,processingDetails)
    # on the uploaded video - readonly is needed for the post-upload
    # verification poll in youtube_upload.wait_until_processed.
    "https://www.googleapis.com/auth/youtube.readonly",
]


def get_credentials() -> Credentials:
    creds: Credentials | None = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"{CREDENTIALS_FILE} not found. Download OAuth Desktop App "
                    "credentials from Google Cloud Console first (see README.md)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds
