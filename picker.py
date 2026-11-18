"""Google Photos Picker API session flow.

The Library API can no longer list a user's existing media (locked down
March 2025), so item selection has to go through an interactive Picker
session: create a session, hand the user a URL to pick items in a browser,
poll until they're done, then list what they picked.
"""

from __future__ import annotations

import time
import webbrowser
from dataclasses import dataclass

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

PICKER_BASE = "https://photospicker.googleapis.com/v1"


@dataclass
class PickedVideo:
    media_item_id: str
    filename: str
    mime_type: str
    base_url: str


def _request_with_backoff(session: AuthorizedSession, method: str, url: str, **kwargs) -> requests.Response:
    delay = 1.0
    for attempt in range(6):
        resp = session.request(method, url, **kwargs)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        time.sleep(delay)
        delay *= 2
    resp.raise_for_status()
    return resp


def create_session(session: AuthorizedSession) -> dict:
    resp = _request_with_backoff(session, "POST", f"{PICKER_BASE}/sessions", json={})
    return resp.json()


def wait_for_selection(session: AuthorizedSession, session_id: str) -> None:
    """Open the picker URL and poll until the user finishes selecting."""
    poll_interval = 3.0
    timeout_seconds = 30 * 60

    resp = _request_with_backoff(session, "GET", f"{PICKER_BASE}/sessions/{session_id}")
    data = resp.json()
    print(f"\nOpen this URL and select your videos (multi-select is fine):\n\n  {data['pickerUri']}\n")
    webbrowser.open(data["pickerUri"])
    print("Waiting for you to finish selecting in the browser...")

    elapsed = 0.0
    while True:
        resp = _request_with_backoff(session, "GET", f"{PICKER_BASE}/sessions/{session_id}")
        data = resp.json()

        polling_config = data.get("pollingConfig", {})
        poll_interval = _duration_to_seconds(polling_config.get("pollInterval")) or poll_interval

        if data.get("mediaItemsSet"):
            return

        if elapsed >= timeout_seconds:
            raise TimeoutError("Timed out waiting for picker selection.")

        time.sleep(poll_interval)
        elapsed += poll_interval


def _duration_to_seconds(duration: str | None) -> float | None:
    if not duration:
        return None
    return float(duration.rstrip("s"))


def list_picked_videos(session: AuthorizedSession, session_id: str) -> list[PickedVideo]:
    videos: list[PickedVideo] = []
    page_token = None

    while True:
        params = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token

        resp = _request_with_backoff(session, "GET", f"{PICKER_BASE}/mediaItems", params=params)
        data = resp.json()

        for item in data.get("mediaItems", []):
            media_file = item.get("mediaFile", {})
            mime_type = media_file.get("mimeType", "")
            if not mime_type.startswith("video/"):
                continue

            metadata = media_file.get("mediaFileMetadata", {})
            video_metadata = metadata.get("videoMetadata", {})
            if video_metadata.get("processingStatus") != "READY":
                print(f"  Skipping {media_file.get('filename')}: not READY yet ({video_metadata.get('processingStatus')}).")
                continue

            videos.append(
                PickedVideo(
                    media_item_id=item["id"],
                    filename=media_file.get("filename", item["id"]),
                    mime_type=mime_type,
                    base_url=media_file["baseUrl"],
                )
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos


def download_video_bytes(session: AuthorizedSession, video: PickedVideo) -> bytes:
    resp = _request_with_backoff(session, "GET", f"{video.base_url}=dv")
    return resp.content


def delete_session(session: AuthorizedSession, session_id: str) -> None:
    try:
        session.delete(f"{PICKER_BASE}/sessions/{session_id}")
    except requests.RequestException:
        pass


def build_authorized_session(creds: Credentials) -> AuthorizedSession:
    return AuthorizedSession(creds)
