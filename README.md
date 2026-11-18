# Google Photos -> YouTube Archiver

Select videos from Google Photos via the Picker API, upload them to YouTube
(private by default), verify the upload actually processed and is playable,
and log the result to `upload_log.csv`.

## Important limitation: there is no auto-delete

Google Photos has never exposed an API to delete or trash arbitrary media
items, and the March 2025 API changes only tightened access further (reads
are now restricted to app-created content too). This is true no matter which
OAuth scope you request. So this tool **cannot** remove anything from your
Google Photos library for you.

Instead, after each verified upload it prints the filename and YouTube link
as a checklist item, and logs `delete_status=manual_pending`, so you can
trash the originals yourself in the Google Photos app or web UI once you're
confident the YouTube copy is good.

## Setup

1. **Create a Google Cloud project**: https://console.cloud.google.com/projectcreate
2. **Enable APIs** (APIs & Services -> Library): enable both
   - "Google Photos Picker API"
   - "YouTube Data API v3"
3. **Create OAuth credentials**: APIs & Services -> Credentials -> Create
   Credentials -> OAuth client ID -> Application type **Desktop app**.
   Download the JSON and save it as `credentials.json` in this folder.
4. **Add yourself as a test user**: APIs & Services -> OAuth consent screen ->
   Audience -> Test users -> add your own Google account email. (The app
   stays "unverified" and Google will show a warning screen on first login —
   click Advanced -> Go to (app name) to proceed; this is expected for an
   app only you use.)
5. **Scopes used** (requested automatically on first run, no manual config
   needed):
   - `https://www.googleapis.com/auth/photospicker.mediaitems.readonly`
   - `https://www.googleapis.com/auth/youtube.upload`

## Install

```
pip install -r requirements.txt
```

## Run

```
python main.py
```

A browser tab opens to Google's Picker UI. Select as many videos as you
want in one session, mark selection done, then return to the terminal.

Options:

```
python main.py --dry-run          # do everything except upload/verify
python main.py --privacy unlisted # default is private
```

First run opens a browser for the OAuth consent flow and caches a refresh
token in `token.json`; later runs are non-interactive until that token is
revoked or expires.

## Output

- `upload_log.csv` — one row per selected video: `original_filename,
  google_photos_id, youtube_video_id, youtube_url, upload_status,
  delete_status, timestamp`.
- Console summary at the end of each run, plus a manual-trash checklist for
  everything that was verified as processed and playable on YouTube.

## Notes

- Uploads are verified via `videos.list(part=status,processingDetails)` —
  a video is only checklisted for manual deletion once YouTube reports
  `uploadStatus=processed` and `processingStatus` succeeded.
- API calls retry with exponential backoff on HTTP 429 (rate limit).
- Picker `baseUrl`s expire 60 minutes after `mediaItems.list` returns them,
  so videos are downloaded and uploaded promptly, one at a time.
