# AI Agent Prompt: Google Photos → YouTube Auto-Archiver

Paste this entire prompt into an AI coding agent (Claude Code, Cursor, etc.) to build the tool.

---

## Project Goal

Build a Python CLI tool that:
1. Lets me select videos from my Google Photos library (via Google's Picker API — this is the only method Google allows since March 2025; full silent library scanning is no longer possible via API).
2. Uploads each selected video to my YouTube channel as **Private** (or Unlisted, configurable).
3. After a successful, verified upload, deletes that video from Google Photos (moves it to Trash, which auto-purges after 60 days — safer than instant permanent delete).
4. Logs everything (what was uploaded, YouTube video ID, original filename, timestamp, delete status) to a local CSV/JSON log file so nothing is lost silently.

## Important Constraints (must respect)

- Google Photos Library API (post-March-2025) **cannot list or scan existing library items automatically**. I must use the **Photos Picker API**, which opens a Google-hosted picker session where I manually select photos/videos (I *can* multi-select many at once in one session — this is fine for my 500+ backlog).
- Do **NOT** attempt to bypass this with scraping, unofficial endpoints, or reverse-engineered mobile APIs. Use only official Google APIs and OAuth 2.0.
- Respect Google API daily quotas: 10,000 requests/day for general calls, 75,000/day for media byte downloads. Add basic rate-limit handling (retry with exponential backoff on HTTP 429).
- Videos must be verified as fully uploaded and playable on YouTube (check upload status via API) BEFORE deleting from Google Photos. Never delete-then-check.
- Default delete action = move to Google Photos Trash, not permanent delete. Add a `--permanent-delete` flag for later, but keep default safe.
- Add a `--dry-run` mode that does everything except the actual delete step, so I can test safely first.

## Tech Stack

- Python 3.11+
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client` for Google OAuth + YouTube Data API v3
- Google Photos Picker API (REST calls via `requests` or `google-api-python-client` if supported)
- `tqdm` for upload progress bars
- Local `credentials.json` (OAuth client secret) + `token.json` (stored refresh token) — standard Google OAuth flow, run once in browser for consent.

## Required Setup Steps (agent should generate instructions for these too)

1. Create a project in Google Cloud Console.
2. Enable: **Photos Picker API** and **YouTube Data API v3**.
3. Create OAuth 2.0 Desktop App credentials, download `credentials.json`.
4. Scopes needed:
   - `https://www.googleapis.com/auth/photospicker.mediaitems.readonly` (or current equivalent — verify exact scope name from latest Google docs)
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata` or the correct scope for trashing Picker-selected items (verify current scope name — Picker API delete permissions may differ; check latest docs)
5. Since app is unverified, I'll need to add my own Google account as a "test user" in the OAuth consent screen.

## Program Flow

```
1. Authenticate (OAuth, refresh token cached in token.json)
2. Start a Picker session -> print/open the picker URL for me to select videos in browser
3. Poll session until I mark selection as done
4. For each selected media item:
   a. Download video bytes (respect base URL + quota)
   b. Upload to YouTube (resumable upload, status=private)
   c. Poll YouTube processing status until "processed" / playable
   d. If success -> log entry -> (unless --dry-run) trash item in Google Photos
   e. If failure -> log error, skip delete, continue to next item
5. Print summary: total processed, uploaded, deleted, failed
```

## Output / Logs

- `upload_log.csv` with columns: `original_filename, google_photos_id, youtube_video_id, youtube_url, upload_status, delete_status, timestamp`
- Console summary at the end of each run.

## Nice-to-haves (only if time permits, not core requirement)

- Config file for default YouTube privacy setting (private/unlisted)
- Simple retry queue for failed uploads on next run
- Basic filter to skip files above a certain size or below a certain duration

## Deliverable

A single well-commented Python script (or small package with 2-3 files: `auth.py`, `main.py`, `youtube_upload.py`) with a `README.md` explaining setup steps 1-5 above and how to run it (`python main.py`, `python main.py --dry-run`).

Do not implement any "watch folder / silent auto-run" feature — this is explicitly not possible via Google's current API and should not be attempted.
