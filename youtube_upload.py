"""Resumable upload to YouTube + polling until the video is verified playable."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from tqdm import tqdm

CHUNK_SIZE = 8 * 1024 * 1024


@dataclass
class UploadResult:
    video_id: str
    url: str
    upload_status: str
    processing_status: str


def build_youtube_client(creds: Credentials):
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, video_bytes: bytes, title: str, privacy_status: str = "private"):
    body = {
        "snippet": {"title": title},
        "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
    }
    media = MediaIoBaseUpload(
        io.BytesIO(video_bytes),
        mimetype="video/*",
        chunksize=CHUNK_SIZE,
        resumable=True,
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    with tqdm(total=len(video_bytes), unit="B", unit_scale=True, desc=title[:40]) as bar:
        last_uploaded = 0
        while response is None:
            status, response = _next_chunk_with_backoff(request)
            if status:
                uploaded = int(status.resumable_progress)
                bar.update(uploaded - last_uploaded)
                last_uploaded = uploaded
        bar.update(len(video_bytes) - last_uploaded)

    return response["id"]


def _next_chunk_with_backoff(request, max_retries: int = 5):
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return request.next_chunk()
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("Exceeded retries uploading chunk.")


def wait_until_processed(youtube, video_id: str, timeout_seconds: int = 30 * 60) -> UploadResult:
    """Poll videos.list until YouTube reports the video processed and playable."""
    poll_interval = 10
    elapsed = 0

    while True:
        resp = youtube.videos().list(part="status,processingDetails", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            raise RuntimeError(f"Video {video_id} not found after upload.")

        status = items[0]["status"]
        processing = items[0].get("processingDetails", {})
        upload_status = status.get("uploadStatus")
        processing_status = processing.get("processingStatus", "unknown")

        if upload_status == "failed" or upload_status == "rejected":
            return UploadResult(video_id, f"https://youtu.be/{video_id}", upload_status, processing_status)

        if upload_status == "processed" and processing_status in ("succeeded", "terminated"):
            return UploadResult(video_id, f"https://youtu.be/{video_id}", upload_status, processing_status)

        if elapsed >= timeout_seconds:
            return UploadResult(video_id, f"https://youtu.be/{video_id}", upload_status, processing_status)

        time.sleep(poll_interval)
        elapsed += poll_interval
