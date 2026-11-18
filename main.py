"""Google Photos -> YouTube archiver.

Select videos via the Photos Picker API, upload each to YouTube (private by
default), verify it actually processed and is playable, and log the result.

IMPORTANT: the Google Photos API has no endpoint to delete or trash media
items (this has never been supported, and the March 2025 lockdown only
tightened things further). This tool cannot remove anything from your
Google Photos library for you. Instead, on success it prints a checklist of
filenames to trash by hand in the Google Photos app/web UI, and records
delete_status=manual_pending in the log so you can track which ones you've
cleared out.
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timezone

import auth
import picker
import youtube_upload

LOG_FILE = "upload_log.csv"
LOG_FIELDS = [
    "original_filename",
    "google_photos_id",
    "youtube_video_id",
    "youtube_url",
    "upload_status",
    "delete_status",
    "timestamp",
]


def append_log(row: dict) -> None:
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive Google Photos videos to YouTube.")
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted"],
        default="private",
        help="YouTube privacy status for uploaded videos (default: private).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except the actual upload; just list what would be uploaded.",
    )
    args = parser.parse_args()

    creds = auth.get_credentials()
    session = picker.build_authorized_session(creds)

    picker_session = picker.create_session(session)
    session_id = picker_session["id"]

    try:
        picker.wait_for_selection(session, session_id)
        videos = picker.list_picked_videos(session, session_id)
    finally:
        picker.delete_session(session, session_id)

    if not videos:
        print("No videos selected (or none were READY yet). Nothing to do.")
        return

    print(f"\n{len(videos)} video(s) selected. Privacy: {args.privacy}. Dry run: {args.dry_run}\n")

    youtube = None if args.dry_run else youtube_upload.build_youtube_client(creds)

    manual_trash_checklist: list[str] = []
    uploaded = failed = 0

    for video in videos:
        timestamp = datetime.now(timezone.utc).isoformat()

        if args.dry_run:
            print(f"[dry-run] Would upload: {video.filename}")
            append_log(
                {
                    "original_filename": video.filename,
                    "google_photos_id": video.media_item_id,
                    "youtube_video_id": "",
                    "youtube_url": "",
                    "upload_status": "dry_run_skipped",
                    "delete_status": "skipped",
                    "timestamp": timestamp,
                }
            )
            continue

        try:
            print(f"Downloading {video.filename}...")
            video_bytes = picker.download_video_bytes(session, video)

            print(f"Uploading {video.filename} to YouTube...")
            video_id = youtube_upload.upload_video(youtube, video_bytes, video.filename, args.privacy)

            print("Waiting for YouTube to finish processing...")
            result = youtube_upload.wait_until_processed(youtube, video_id)

            success = result.upload_status == "processed" and result.processing_status in ("succeeded", "terminated")
            upload_status = f"{result.upload_status}/{result.processing_status}"
            delete_status = "manual_pending" if success else "skipped_not_verified"

            append_log(
                {
                    "original_filename": video.filename,
                    "google_photos_id": video.media_item_id,
                    "youtube_video_id": video_id,
                    "youtube_url": result.url,
                    "upload_status": upload_status,
                    "delete_status": delete_status,
                    "timestamp": timestamp,
                }
            )

            if success:
                uploaded += 1
                manual_trash_checklist.append(f"{video.filename}  ->  {result.url}")
                print(f"  OK: {result.url} (verified {upload_status})")
            else:
                failed += 1
                print(f"  NOT verified ({upload_status}) - leaving in Google Photos, not queuing for trash.")

        except Exception as e:  # noqa: BLE001 - log and continue with the rest of the batch
            failed += 1
            print(f"  FAILED: {video.filename}: {e}")
            append_log(
                {
                    "original_filename": video.filename,
                    "google_photos_id": video.media_item_id,
                    "youtube_video_id": "",
                    "youtube_url": "",
                    "upload_status": f"error: {e}",
                    "delete_status": "skipped_error",
                    "timestamp": timestamp,
                }
            )

    print("\n--- Summary ---")
    print(f"Selected: {len(videos)}  Uploaded+verified: {uploaded}  Failed: {failed}")
    print(f"Log written to: {os.path.abspath(LOG_FILE)}")

    if manual_trash_checklist:
        print(
            "\nGoogle Photos has no API for deleting/trashing media items, so this "
            "step is manual. Verified uploads below are safe to trash by hand "
            "(search Google Photos by filename):\n"
        )
        for line in manual_trash_checklist:
            print(f"  [ ] {line}")


if __name__ == "__main__":
    main()
