# ChapterBox

Turn local PDF, EPUB, and UTF-8 TXT documents into audiobooks using your existing Chatterbox server. All speech generation is sequential and runs through the server at `http://127.0.0.1:4123`.

## Start here

Double-click **Run ChapterBox.bat** in this folder. Choose **1. Convert a document**, then drag a PDF, EPUB, or TXT file into the window and press Enter. ChapterBox copies the original into `input/` and saves narration text in `prepared/`. Review the preview, choose **E** to edit in Notepad, save and close the editor, then choose **G** to generate. Finished audio appears in its own folder under `output/`. Menu option **7** opens that folder.

You can also put files into `input/pdf`, `input/epub`, or `input/text`. Menu option **2** processes these documents automatically after asking whether to skip individual previews. A bad document is logged and the batch continues; a server connection failure stops the batch.

## Your recovered audiobook

**`output/The_Mimis/The_Mimis.wav`** contains all 60 original chunks in order: **549.72 seconds (9 minutes, 9.72 seconds)**, mono, 24,000 Hz, 16-bit PCM. No narration was regenerated for this recovery.

The original chunks were valid **32-bit floating-point WAVs**. The old Python WAV reader rejected that format. Its output writer then raised `# channels not specified` while closing, masking the read failure and leaving an empty output. The new decoder supports PCM 8/16/24/32-bit, float 32/64-bit, and corresponding extensible WAV formats. Merging normalizes sample rates and channels and replaces the final file only after successful assembly.

Everything in `raw/` is retained byte-for-byte as a historical backup, including the original converter and its empty WAV. Use the new launcher; the historical converter has the old behavior. `logs/recovery.json` records hashes of every original file and the format of each chunk. Verified copies of the chunks are under `cache/The_Mimis_legacy-.../chunks/`. The prepared text and original PDF also have organized copies.

## Requirements and setup

- Windows and Python **3.11 or newer**. The launcher looks for 3.11 first when creating an environment, then other installed Windows Python versions. This machine currently has Python 3.14; ChapterBox was tested with that version.
- ChapterBox uses its own `.venv`. It never installs anything into Chatterbox's environment.
- PDF extraction needs **pypdf**. The launcher asks before installing it into ChapterBox's environment. Declining still allows TXT and EPUB work. Network access is needed only for this dependency installation.
- WAV processing and EPUB extraction use the Python standard library.
- Optional MP3 export needs **FFmpeg** on PATH with the `libmp3lame` encoder. It is not installed automatically. WAV output is retained if MP3 export fails.

## Preparing documents

Original files stay unchanged. A content hash distinguishes documents with the same name. Importing the same document again preserves your existing prepared-text edits.

PDF cleanup joins wrapped lines, removes repeated first/last margin lines and page numbers, and removes discretionary soft hyphens. Ordinary word-ending hyphens remain because guessing whether a word was hyphenated could change the author's wording. PDF extraction cannot reliably infer every paragraph, multi-column reading order, or header; always review the prepared text.

If any PDF page has no extractable text, ChapterBox stops with the page numbers instead of silently skipping it. Scanned PDFs need an external OCR tool to produce a searchable copy. OCR is not bundled or run automatically. Blank pages may trigger the same check; remove them from a copy before importing. Password-protected PDFs need an unlocked copy.

EPUB files follow the spine reading order. Chapter document boundaries appear as `=== CHAPTER BREAK ===` in the editable narration. Keep these markers to get separate chapter WAVs as well as the combined book. The markers are not spoken. TXT preserves UTF-8 accents, dialogue, and paragraph boundaries. ChapterBox never summarizes or rewrites narration.

## Resume and recovery

Press **Ctrl+C** to cancel. Successful chunks remain saved. Choose **3. Resume unfinished audiobook** to continue with that job's saved text and settings. A request already accepted by the server may continue on the CPU after cancellation; wait for it to finish before restarting work.

Changing a prepared text or generation settings creates a separate cache when you convert it again. Resume deliberately uses the original job snapshot. Each cached chunk has a SHA-256 hash and a fingerprint of its text and speech settings; audio is decoded and validated before reuse. Only missing, changed, or corrupt chunks are requested again. Invalid older files are preserved with an `.invalid` suffix. Do not manually edit manifests.

Choose **4. Merge existing audio chunks** and provide a cache job folder to validate and assemble it. Missing or corrupt chunks in a managed job can be regenerated using its saved configuration. For a standalone folder, use numbered `part_0001.wav`, `part_0002.wav`, etc.; numbering gaps and legacy manifest count mismatches stop the merge. Standalone chunks without a manifest must be checked by you for completeness.

Merges use temporary files and atomic replacement. Failed merges leave caches and previous finished audio intact. An OS file lock prevents two processes from writing the same audiobook cache simultaneously. Run only one conversion at a time to avoid overloading your CPU server.

## Settings and server

Menu option **8** opens `config.json` in Notepad. Save valid JSON. Main settings:

| Setting | Purpose |
| --- | --- |
| `endpoint` | Existing API speech URL; default is `/v1/audio/speech` on port 4123 |
| `chunk_chars` | 50–1000; default 220 is suitable for the current server's 280-character chunk preference |
| `model`, `voice` | Sent to the server and included in the cache fingerprint |
| `parameters` | Optional `exaggeration`, `cfg_weight`, `temperature`, and `speed` |
| `retries`, `timeout` | Transient request retries (1–10) and per-request timeout in seconds |
| `sample_rate`, `channels` | Final PCM16 format; default 24000 Hz, mono; stereo is also supported |
| `paragraph_pause`, `chapter_pause` | Added silence in seconds, from 0 through 30 |
| `mp3` | Set `true` to additionally export MP3 using installed FFmpeg |
| `server_directory` | Existing Chatterbox repository to launch only when requested |

The running server's schema says `voice` and `speed` are ignored and the configured voice sample is used. `model` is accepted as a compatibility field but is not a selectable model in this server's request schema. ChapterBox cannot make those options effective unless the server supports them. The current supported tuning ranges are exaggeration 0.25–2, cfg_weight 0–1, and temperature 0.05–5.

Menu option **6** checks the server's health. If unavailable, it offers to launch the existing `start.py` using the existing server environment, without installing or changing anything. Startup diagnostics go to `logs/server-start.log`. It never restarts a reachable server.

**Current environment note:** the server is healthy and running on CPU, but its saved `.venv` launcher points to a missing Python 3.11 executable. The running process was left untouched. Launching that environment after it stops will need separate repair; ChapterBox reports the launcher error instead of changing it automatically.

For connection problems, verify the endpoint, check menu option 6, and read `logs/chapterbox.log`. HTTP validation errors stop immediately; temporary server errors retry with backoff. CPU narration may take much longer than the audio duration.

## Folder guide

| Folder | Contents |
| --- | --- |
| `app/` | Application code and launcher setup |
| `input/pdf`, `input/epub`, `input/text` | Original document copies and incoming files |
| `prepared/` | Editable narration text |
| `cache/<job>/` | Narration snapshot, manifest, and reusable audio chunks |
| `output/<book>/` | Combined WAV, optional MP3, and EPUB chapter WAVs |
| `logs/` | Tracebacks, recovery audit, and test results |
| `raw/` | Untouched historical project files |
| `tests/` | Automated tests and tiny live-test fixture |

Resampling uses linear interpolation; multichannel input is averaged for mono, and mono is duplicated for stereo. This keeps dependencies small but is not a mastering-grade resampler. Classic WAV's size limit is about 4 GB; larger books need to be split into separate source documents. No complete audiobook generation was run during testing.

## Automated checks and optional command line

From this folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe tests\run_tests.py
.\.venv\Scripts\python.exe -m app.main "C:\path with spaces\book.epub" --prepare-only
.\.venv\Scripts\python.exe -m app.main "C:\path with spaces\book.txt" --auto
.\.venv\Scripts\python.exe -m app.main --resume "cache\job-name\manifest.json"
```

The test suite uses synthetic WAVs and mocked API failures. Results are saved to `logs/automated-tests.txt`; expected simulated failure tracebacks go to `logs/test-errors.log`. All **17 tests passed**, including PDF extraction, paragraph preservation, and scanned-page detection, with pypdf 6.21.2 installed in ChapterBox's environment. The original five-page PDF was also extracted to `prepared/The_Mimis_2_5_-_Tagged-dfecf5f748f3.txt`; this includes the source PDF's introductory author biography, so review it before narration. The live test generated only **two short chunks** and produced a valid **3.1-second WAV** under `output/live_sample-.../`. Cold server startup, MP3 encoding without FFmpeg, and Python 3.11 execution are not verified on this machine.
