# EcoEvo Job Searcher

Website for ecology & evolution job listings from **ecoevojobs**, **EvolDir**, and **Science Careers**.

## Live site

**https://calcharp.github.io/EcoEvoJobSearcher/**

Browse, filter, map, and explore subject terms — no install needed.

Listings refresh when the **Deploy GitHub Pages** workflow runs (daily at noon UTC, or manually from the Actions tab). First-time setup: repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

## Build the site locally

Requires Python 3.12+:

```bash
git clone https://github.com/calcharp/EcoEvoJobSearcher.git
cd EcoEvoJobSearcher
pip install -r requirements.txt
python scripts/publish_static.py --out _site --base-path ./
# Preview: python -m http.server 8080 --directory _site
```

Options:

- `--no-scrape` — reuse existing local database without scraping
- `--skip-geocode` — skip geocoding for a quick test
- `--geocode-limit N` — geocode at most N places this run (default: all pending)

## Maintainer workflow

| Workflow | Trigger | Output |
|----------|---------|--------|
| **Deploy GitHub Pages** | Push to `main`, daily schedule, manual | Live site |

The workflow caches `jobs.db` between runs so geocoding results accumulate. Geocoding uses parallel requests (Photon, with Nominatim fallback) with no artificial cap during deploy.

## Data storage

Build-time SQLite database (used only in CI / local publish):

| Platform | Location |
|----------|----------|
| Windows | `%LOCALAPPDATA%\JobBoards\jobs.db` |
| macOS | `~/Library/Application Support/JobBoards/jobs.db` |
| Linux | `~/.local/share/JobBoards/jobs.db` |

The published site is static JSON + HTML on GitHub Pages.
