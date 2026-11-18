# Follow-up prompt: Fully automated version (Playwright)

Paste this into the same Claude Code session (it already has full context of the existing project).

---

## Goal

Extend the existing tool (auth.py, picker.py, youtube_upload.py, main.py) with a new fully-automated mode that requires **zero manual video selection** in Google Photos, using real browser automation instead of the Picker API. This replaces the Picker-based selection step; the YouTube upload/verify logic should be reused as-is.

## Why

The Photos Picker API requires a human to manually select items in a browser dialog every run. I want a mode where the tool logs into Google Photos itself, scrolls/lists all videos, and processes them one by one without me clicking anything, including deleting from Google Photos (moving to Trash) after a verified upload — since there is no official API for that either.

## Requirements

- Use **Playwright for Python** (`playwright` package), Chromium channel.
- On first run, launch a **non-headless** browser window so I can log into Google manually (including 2FA if prompted). After login, persist the session using Playwright's `launch_persistent_context` pointed at a local folder (e.g. `./browser_profile/`) so future runs are already logged in and don't need headless=False every time.
- Add a new script `auto_migrate.py` that:
  1. Opens `photos.google.com` using the persisted profile.
  2. Locates and iterates over video items in the library (filter to videos only, not photos — Google Photos has a way to filter by "Videos" in search/filter).
  3. For each video not already logged as `uploaded_and_verified` in `upload_log.csv` (to avoid reprocessing):
     - Downloads or extracts the video (use whatever method is feasible via the UI, e.g. triggering the "Download" action and waiting for the file to land in a designated downloads folder)
     - Calls the existing `youtube_upload.py` logic to upload as private and poll until verified processed/playable
     - If verified: clicks into the item in Google Photos and uses the UI to move it to Trash
     - If upload fails: skip deletion, log the failure, continue to the next item
  4. Logs every action to the same `upload_log.csv` format as before, plus a `method: automated` column to distinguish from Picker-based runs.
  5. Add random small delays (1-3 seconds) between UI actions to behave more like a human and reduce the chance of being flagged.
  6. Wrap all Playwright interactions in try/except so one broken selector doesn't crash the whole run — log the error for that item and continue.
  7. Add a `--limit N` flag to process only N videos per run, and a `--dry-run` flag matching the existing pattern (does everything except the actual Trash click).

## Important constraints

- Do not attempt to bypass Google login/2FA programmatically — the human must complete login manually the first time in the visible browser window.
- Do not hardcode credentials anywhere in the code or logs.
- Since this relies on Google Photos' web UI structure (CSS selectors, element roles), clearly comment every selector so it's easy for me to find and fix them later if Google changes their UI and something breaks.
- Keep this as a separate mode/script from the existing Picker-based `main.py` — don't remove or break the working Picker-based flow. I want both available.
- Update README.md with a new section explaining: how to install Playwright (`pip install playwright` + `playwright install chromium`), how first-run login works, and a troubleshooting note that says "if this script stops working, Google likely changed their UI — selectors in auto_migrate.py will need updating."

## Deliverable

- `auto_migrate.py`
- Updated `requirements.txt` with `playwright` added
- Updated `README.md` with the new section
- Brief summary of any selectors/assumptions you made about Google Photos' current UI, so I know what to check first if it breaks later
