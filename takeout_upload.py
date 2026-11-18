"""Upload videos from Google Takeout export zips to YouTube.

This is the bulk alternative to the Picker-based main.py: instead of
manually selecting videos in a browser each run, you request a Google
Takeout export of Google Photos (https://takeout.google.com), and this
script walks whatever .zip parts have finished downloading, uploads every
video inside to YouTube, verifies it, and logs it - same CSV format and
same verify-before-anything logic as main.py.

Takeout splits large exports into multiple zip parts and they can take a
long time to download. This script does NOT need to wait for the full
export: run it anytime, it processes whatever parts exist and skips ones
it has already fully handled (tracked in takeout_processed_zips.txt) plus
anything already logged as uploaded (tracked in upload_log.csv). Re-run it
again later as more parts finish downloading.

Deletion from Google Photos still has no API (see README.md) - this stays
manual, same as the Picker flow.
"""

from __future__ import annotations

import argparse
import csv
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError

import auth
import youtube_upload

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}

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

PROCESSED_ZIPS_FILE = "takeout_processed_zips.txt"
DEFAULT_TMP_DIR = "takeout_tmp"


class QuotaExceeded(Exception):
    """Raised when the YouTube Data API daily quota has been used up."""


def _raise_if_quota_exceeded(e: Exception) -> None:
    if isinstance(e, HttpError) and e.resp.status == 403:
        body = str(e)
        if "quotaExceeded" in body or "dailyLimitExceeded" in body:
            raise QuotaExceeded(str(e)) from e


def load_already_uploaded_filenames() -> set[str]:
    if not os.path.exists(LOG_FILE):
        return set()
    done = set()
    with open(LOG_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("upload_status", "").startswith("processed/"):
                done.add(row["original_filename"])
    return done


def load_processed_zips() -> set[str]:
    if not os.path.exists(PROCESSED_ZIPS_FILE):
        return set()
    with open(PROCESSED_ZIPS_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_zip_processed(zip_name: str) -> None:
    with open(PROCESSED_ZIPS_FILE, "a", encoding="utf-8") as f:
        f.write(zip_name + "\n")


def append_log(row: dict) -> None:
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def find_takeout_zips(downloads_dir: Path) -> list[Path]:
    return sorted(downloads_dir.glob("takeout-*.zip"))


def is_zip_complete(zip_path: Path) -> bool:
    """A part still downloading won't open as a valid zip (or its central
    directory / CRCs won't check out) - use that as the "is it done yet"
    signal instead of relying on Chrome's .crdownload naming."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def iter_video_entries(zf: zipfile.ZipFile):
    for info in zf.infolist():
        if info.is_dir():
            continue
        ext = Path(info.filename).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            yield info


def process_zip(zf, zip_path, args, tmp_dir, already_uploaded, counters, manual_trash_checklist, youtube):
    """Process every not-yet-uploaded video in one zip. Returns True if the
    whole zip was walked (vs. stopped early because --limit was hit)."""
    zip_fully_done = True

    for entry in iter_video_entries(zf):
        filename = Path(entry.filename).name

        if filename in already_uploaded:
            print(f"  Skipping {filename}: already uploaded+verified.")
            continue

        if args.limit is not None and counters["attempted"] >= args.limit:
            zip_fully_done = False
            break

        counters["attempted"] += 1
        timestamp = datetime.now(timezone.utc).isoformat()

        if args.dry_run:
            print(f"  [dry-run] Would upload: {filename}")
            append_log(
                {
                    "original_filename": filename,
                    "google_photos_id": entry.filename,
                    "youtube_video_id": "",
                    "youtube_url": "",
                    "upload_status": "dry_run_skipped",
                    "delete_status": "skipped",
                    "timestamp": timestamp,
                }
            )
            continue

        extracted_path = tmp_dir / filename
        try:
            print(f"  Extracting {filename}...")
            with zf.open(entry) as src, open(extracted_path, "wb") as dst:
                dst.write(src.read())

            print(f"  Uploading {filename} to YouTube...")
            video_bytes = extracted_path.read_bytes()
            video_id = youtube_upload.upload_video(youtube, video_bytes, filename, args.privacy)

            print("  Waiting for YouTube to finish processing...")
            result = youtube_upload.wait_until_processed(youtube, video_id)

            success = result.upload_status == "processed" and result.processing_status in ("succeeded", "terminated")
            upload_status = f"{result.upload_status}/{result.processing_status}"
            delete_status = "manual_pending" if success else "skipped_not_verified"

            append_log(
                {
                    "original_filename": filename,
                    "google_photos_id": entry.filename,
                    "youtube_video_id": video_id,
                    "youtube_url": result.url,
                    "upload_status": upload_status,
                    "delete_status": delete_status,
                    "timestamp": timestamp,
                }
            )

            if success:
                counters["uploaded"] += 1
                already_uploaded.add(filename)
                manual_trash_checklist.append(f"{filename}  ->  {result.url}")
                print(f"    OK: {result.url} (verified {upload_status})")
            else:
                counters["failed"] += 1
                print(f"    NOT verified ({upload_status}).")

        except QuotaExceeded:
            raise

        except Exception as e:  # noqa: BLE001 - log and keep going, unless it's quota
            _raise_if_quota_exceeded(e)
            counters["failed"] += 1
            print(f"    FAILED: {filename}: {e}")
            append_log(
                {
                    "original_filename": filename,
                    "google_photos_id": entry.filename,
                    "youtube_video_id": "",
                    "youtube_url": "",
                    "upload_status": f"error: {e}",
                    "delete_status": "skipped_error",
                    "timestamp": timestamp,
                }
            )
        finally:
            extracted_path.unlink(missing_ok=True)

    return zip_fully_done


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload videos from Google Takeout export zips to YouTube.")
    parser.add_argument("--downloads-dir", default="D:\\", help="Folder to scan for takeout-*.zip parts (default: D:\\).")
    parser.add_argument("--tmp-dir", default=DEFAULT_TMP_DIR, help="Scratch folder for extracted videos before upload.")
    parser.add_argument("--privacy", choices=["private", "unlisted"], default="private")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except the actual upload.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many upload attempts.")
    args = parser.parse_args()

    downloads_dir = Path(args.downloads_dir)
    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    zips = find_takeout_zips(downloads_dir)
    if not zips:
        print(f"No takeout-*.zip files found in {downloads_dir}.")
        return

    already_uploaded = load_already_uploaded_filenames()
    processed_zips = load_processed_zips()

    creds = auth.get_credentials()
    youtube = None if args.dry_run else youtube_upload.build_youtube_client(creds)

    manual_trash_checklist: list[str] = []
    counters = {"uploaded": 0, "failed": 0, "skipped_zips": 0, "attempted": 0}
    quota_hit = False

    try:
        for zip_path in zips:
            if zip_path.name in processed_zips:
                counters["skipped_zips"] += 1
                continue

            if not is_zip_complete(zip_path):
                print(f"Skipping {zip_path.name}: still downloading / incomplete.")
                continue

            print(f"\n=== {zip_path.name} ===")

            with zipfile.ZipFile(zip_path) as zf:
                zip_fully_done = process_zip(
                    zf, zip_path, args, tmp_dir, already_uploaded, counters, manual_trash_checklist, youtube
                )

            if zip_fully_done and not args.dry_run:
                mark_zip_processed(zip_path.name)

            if args.limit is not None and counters["attempted"] >= args.limit:
                break

    except QuotaExceeded as e:
        quota_hit = True
        print(f"\nYouTube API daily quota exceeded: {e}")
        print(
            "Default project quota is 10,000 units/day and each upload (videos.insert) "
            "costs 1,600 units - roughly 6 uploads/day on a fresh project. Wait for the "
            "quota to reset (~midnight Pacific Time) or request a quota increase in "
            "Google Cloud Console, then re-run this script - it resumes where it left off "
            "(already-verified uploads are skipped via upload_log.csv)."
        )

    print("\n--- Summary ---")
    print(f"Zip parts already fully processed (skipped): {counters['skipped_zips']}")
    print(f"Uploaded+verified this run: {counters['uploaded']}  Failed: {counters['failed']}")
    print(f"Log written to: {os.path.abspath(LOG_FILE)}")

    if manual_trash_checklist:
        print(
            "\nGoogle Photos has no API for deleting/trashing media items, so this "
            "step is manual. Verified uploads below are safe to trash by hand "
            "(search Google Photos by filename):\n"
        )
        for line in manual_trash_checklist:
            print(f"  [ ] {line}")

    if not quota_hit:
        remaining = [z for z in find_takeout_zips(downloads_dir) if z.name not in load_processed_zips()]
        if remaining:
            print(f"\n{len(remaining)} zip part(s) still pending/incomplete - re-run this script later to pick them up.")


if __name__ == "__main__":
    main()
