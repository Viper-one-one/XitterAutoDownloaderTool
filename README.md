# XitterAutoDownloaderTool

A desktop application built with Python and PySide6 for automatically archiving and downloading videos from your X (formerly Twitter) bookmarks.

The tool uses your existing Firefox browser session to securely authenticate with X without requiring you to enter your account credentials. It navigates your bookmarks using Playwright, detects video content, and downloads media using yt-dlp and FFmpeg.

---

## Features

- Firefox Profile Integration: Reads session cookies directly from your local Firefox profile in a lock-safe manner, avoiding manual password entry or session token configuration.
- Automated Bookmark Scrolling: Uses Playwright to traverse your bookmark feed and extract tweet metadata and media links.
- Smart Cutoff and Anchor Stop: Remembers the last processed bookmark and stops crawling once known items are reached, saving time and bandwidth.
- Date Range Filtering: Filter bookmarks by custom date ranges or automatically stop after encountering consecutive items older than your target date.
- Configurable Media Capture: Supports standard tweet videos, GIFs, and optional extraction of quoted tweet videos.
- High-Performance Downloads: Leverages yt-dlp for reliable, multi-threaded downloading with support for resume and duplicate prevention via archive files.
- Desktop GUI: Clean PySide6 graphical interface with a progress table, real-time logging, and customizable settings.

---

## Prerequisites

Before installing and running the application, ensure the following prerequisites are installed:

1. Python 3.10 or higher.
2. Mozilla Firefox with an active login session on [x.com](https://x.com).
3. FFmpeg installed and accessible from your system PATH (required by yt-dlp for merging audio and video streams).

### Installing FFmpeg

- Windows:
  - Using winget:
    ```powershell
    winget install Gyan.FFmpeg
    ```
  - Using Chocolatey:
    ```powershell
    choco install ffmpeg
    ```
  - Alternatively, download a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin` directory to your system environment `PATH`.

- macOS:
  ```bash
  brew install ffmpeg
  ```

- Linux (Debian/Ubuntu):
  ```bash
  sudo apt update && sudo apt install ffmpeg
  ```

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Viper-one-one/XitterAutoDownloaderTool.git
cd XitterAutoDownloaderTool
```

### 2. Create and Activate a Virtual Environment

- Windows (PowerShell):
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```

- Windows (Command Prompt):
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate.bat
  ```

- Linux / macOS:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install Playwright Firefox Browser

Playwright requires its dedicated browser binary to automate bookmark extraction:

```bash
playwright install firefox
```

---

## How to Use

### Step 1: Ensure Firefox is Logged In

1. Open Mozilla Firefox on your computer.
2. Navigate to [x.com](https://x.com) and ensure your account is logged in and bookmarks are viewable.
3. You do not need to keep Firefox open, but your login session must be active in your Firefox profile.

### Step 2: Launch the Application

- On Windows, double-click `run.bat` or launch from terminal:
  ```cmd
  run.bat
  ```

- Cross-platform via Python:
  ```bash
  python main.py
  ```

### Step 3: Configure Settings

1. Firefox Profile:
   - The application automatically detects installed Firefox profiles. Select the profile that holds your logged-in X session from the dropdown.
   - If your profile is stored in a non-standard location, click Browse to locate the profile directory manually.
2. Output Directory:
   - Select the target folder where downloaded video files will be saved (defaults to `~/Videos/XBookmarks`).
3. Stopping and Filtering Options:
   - Anchor Stop: When enabled, crawling stops once the application encounters the bookmark from your previous run.
   - Date Filter: Set a start and end date to restrict archiving to tweets published within a specific window.
   - Consecutive Old Limit: Automatically stops scrolling after encountering a set number of consecutive tweets older than your date cutoff.
4. Media Options:
   - Include GIFs: Toggle downloading animated MP4 GIFs.
   - Include Quoted Videos: Toggle downloading videos attached inside quoted tweets.
5. Download Settings:
   - Concurrency: Set the number of simultaneous video downloads (default: 2).
   - Filename Template: Customize the yt-dlp naming format (e.g., `%(uploader_id)s - %(upload_date)s - %(id)s.%(ext)s`).
   - Format Selector: Select the desired stream quality selector passed to yt-dlp.

### Step 4: Run the Extraction and Download

1. Click Start Run.
2. The application will launch an automated session, navigate to your bookmarks feed, and extract tweet entries matching your criteria.
3. Discovered items will populate the main table, showing the tweet ID, author, date, download status, file size, and progress.
4. Downloads will execute concurrently as items are discovered.
5. Click Stop Run at any point to gracefully finish active tasks and exit the browser session.

---

## Troubleshooting

- Playwright Firefox missing:
  Run `playwright install firefox` inside your active virtual environment.

- FFmpeg not found:
  Verify FFmpeg is installed by opening a terminal and running `ffmpeg -version`. Ensure the folder containing `ffmpeg.exe` (or the Unix binary) is added to your system `PATH`.

- Not logged in / Session not detected:
  Ensure you are using the correct Firefox profile. If you have multiple profiles, check `about:profiles` in Firefox to identify the profile currently in use.

- Missing or incomplete downloads:
  Check the application log pane at the bottom of the window for specific error messages or HTTP status responses from X or yt-dlp.

---

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file located in the root of this repository.
