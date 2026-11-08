# RAG App

Status: Working

## What it does
A local knowledge base for PDF, Word, Excel, CSV and image files. It indexes your documents (with OCR and page previews), then lets an AI assistant search them by exact words and by meaning, and cite the exact page or row. Everything runs on your own computer; no paid services or API keys.

## Install and run

### Windows

#### Downloadable app
1. Open **Releases** (right-hand side of this page) and download `RAG-Knowledge-Base-Windows-x86_64.zip`. Unzip it to a folder you can write to, such as Documents, and keep the files together.
2. Double-click `RAG Knowledge Base.exe`. Because the build is not signed with a paid certificate, Windows may say "Windows protected your PC": click **More info**, then **Run anyway**.
3. Put documents in the `Sync Library` folder next to the app (created on first launch), open the app, and click **Sync Library**.

#### Run from source
You need [Python](https://www.python.org/downloads/windows/) installed first (the tests run on Python 3.12). On this page, click **Code → Download ZIP**, unzip it, then:

1. Open the `src` folder (this is the whole app).
2. Run `setup.ps1` once (creates the Python environment and downloads the search model). For an NVIDIA GPU, also run `setup_gpu.ps1`.
3. Run `build_app.ps1` to create `RAG Knowledge Base.exe`, or just run `run_app.ps1`.
4. Put the documents you want searchable in `src\Sync Library` (or change `sync_library` in `src\settings.json`), then click **Sync Library** in the app.

### macOS

#### Downloadable app
1. Open the repository's **Actions** page and select a successful **Build** run, or download a tagged version from **Releases**.
2. Download the ZIP matching the Mac: `arm64` for Apple silicon (M1 or newer), or `x86_64` for an Intel Mac.
3. Unzip it and move **RAG Knowledge Base.app** to Applications. Because the build is not notarized with an Apple Developer certificate, first launch it by Control-clicking the app, choosing **Open**, and confirming.
4. Put documents in `~/Library/Application Support/RAG Knowledge Base/Sync Library`, open the app, and click **Sync Library**.

#### Run from source
1. Open Terminal, change to the repository's `src` folder, and run `chmod +x setup_macos.sh run_app_macos.command run_mcp_macos.sh build_macos.sh`.
2. Run `./setup_macos.sh` once.
3. Double-click `run_app_macos.command`, or run it from Terminal.
4. Optional OCR requires Tesseract; with Homebrew, install it using `brew install tesseract`.

### Linux
Not supported yet.

## Notes
- The sync folder is **`src\Sync Library`**, inside the app's own folder. It starts empty and is not stored in GitHub, and neither are the database (`src\data`), model cache, or built `.exe` files; they are created on your computer.
- A packaged macOS app stores its writable files in `~/Library/Application Support/RAG Knowledge Base`. The desktop app and MCP executable share that location.
- Full guide: `docs/APP_GUIDE.md`. Instructions for AI assistants (any AI tool): `AGENTS.md` for working on this repository, and `src/LLM_INSTRUCTIONS.md` for using the knowledge base.
- OCR needs Tesseract. Install it from https://github.com/UB-Mannheim/tesseract/wiki, or copy a portable Tesseract into `src\tools\tesseract` (not stored in GitHub, about 112 MB).
- The optional GPU environment (`gpu-venv`) is created by `setup_gpu.ps1` inside the app folder.
- Tests: run `python -m unittest discover -s tests` from `src`.

## License
MIT. You are free to view, copy, download, modify and share this code. See `LICENSE`.
