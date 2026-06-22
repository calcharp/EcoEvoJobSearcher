# EcoEvo Job Searcher

Local app for ecology & evolution job listings from **ecoevojobs**, **EvolDir**, and **Science Careers**.

Opens your default browser, scrapes on launch, and keeps everything in a local SQLite database. Close the browser tab to exit.

## Download (easiest)

Pre-built executables are attached to [GitHub Releases](https://github.com/calcharp/EcoEvoJobSearcher/releases):

| Platform | Download |
|----------|----------|
| Windows | `JobBoards-windows-x64.zip` → run `JobBoards.exe` |
| macOS (Apple Silicon) | `JobBoards-macos-arm64.zip` → run `JobBoards` |
| Linux | `JobBoards-linux-x64.zip` → run `./JobBoards` |

On macOS/Linux you may need to mark the binary executable (`chmod +x JobBoards`). Unsigned macOS builds may require right-click → Open the first time.

## Run from source

Requires **Python 3.10+**.

```bash
git clone https://github.com/calcharp/EcoEvoJobSearcher.git
cd EcoEvoJobSearcher
pip install -r requirements.txt
python main.py
```

## Build your own executable

One command after cloning (use a **virtual environment** for a smaller binary — ~20–30 MB vs 70+ MB from a bloated system Python):

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
python build.py
```

Output lands in `dist/` (`JobBoards.exe` on Windows, `JobBoards` elsewhere). The script installs PyInstaller automatically if needed.

Manual build:

```bash
pip install -r requirements.txt -r requirements-build.txt
pyinstaller JobBoards.spec --noconfirm --clean
```

## Publishing releases (maintainers)

Tag a version to build all three platforms and attach zips to a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Or run the **Release** workflow manually from the Actions tab.

## Data storage

| Platform | Location |
|----------|----------|
| Windows | `%LOCALAPPDATA%\JobBoards\jobs.db` |
| macOS | `~/Library/Application Support/JobBoards/jobs.db` |
| Linux | `~/.local/share/JobBoards/jobs.db` (or `$XDG_DATA_HOME/JobBoards`) |

Saved jobs, dismissed listings, and saved searches live in the same database.
