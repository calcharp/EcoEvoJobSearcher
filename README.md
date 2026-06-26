# EcoEvo Job Searcher

Local app and **GitHub Pages** site for ecology & evolution job listings from **ecoevojobs**, **EvolDir**, and **Science Careers**.

## Live site (GitHub Pages)

**https://calcharp.github.io/EcoEvoJobSearcher/**

No install needed — browse, filter, map, subject cloud, save/dismiss jobs (stored in your browser).

Listings refresh when the **Deploy GitHub Pages** workflow runs (daily at noon UTC, or manually from the Actions tab). First-time setup: repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Local app

Opens your default browser, scrapes on launch, and keeps everything in a local SQLite database. Close the browser tab to exit.

```bash
git clone https://github.com/calcharp/EcoEvoJobSearcher.git
cd EcoEvoJobSearcher
pip install -r requirements.txt
python main.py
```

## Download executable

Pre-built binaries are on [GitHub Releases](https://github.com/calcharp/EcoEvoJobSearcher/releases):

| Platform | Download |
|----------|----------|
| Windows | `JobBoards-windows-x64.zip` → run `JobBoards.exe` |
| macOS (Apple Silicon) | `JobBoards-macos-arm64.zip` → run `JobBoards` |
| Linux | `JobBoards-linux-x64.zip` → run `./JobBoards` |

## Build executable locally

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
python build.py
```

## Build static site locally

Reuses your local `jobs.db` (or scrapes fresh if omitted):

```bash
pip install -r requirements.txt
python scripts/publish_static.py --out _site --base-path ./
# Preview: python -m http.server 8080 --directory _site
```

Options: `--no-scrape` (use existing DB), `--geocode-limit 0` (skip geocoding for a quick test).

## Maintainer workflows

| Workflow | Trigger | Output |
|----------|---------|--------|
| **Deploy GitHub Pages** | Push to `main`, daily schedule, manual | Live site |
| **Release** | Tag `v*` | Windows / macOS / Linux zips |

## Data storage

**Local app** — SQLite:

| Platform | Location |
|----------|----------|
| Windows | `%LOCALAPPDATA%\JobBoards\jobs.db` |
| macOS | `~/Library/Application Support/JobBoards/jobs.db` |
| Linux | `~/.local/share/JobBoards/jobs.db` |

**GitHub Pages** — saved/dismissed jobs and saved searches use `localStorage` in your browser only.
