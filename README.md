# RAG App

Status: Working

## What it does
A local knowledge base for PDF, Word, Excel, CSV and image files. It indexes your documents (with OCR and page previews), then lets an AI assistant search them by exact words and by meaning, and cite the exact page or row. Everything runs on your own computer; no paid services or API keys.

## Install and run

### Windows
1. Open the `src` folder (this is the whole app).
2. Run `setup.ps1` once (creates the Python environment and downloads the search model). For an NVIDIA GPU, also run `setup_gpu.ps1`.
3. Run `build_app.ps1` to create `RAG Knowledge Base.exe`, or just run `run_app.ps1`.
4. Put the documents you want searchable in `src\Sync Library` (or change `sync_library` in `src\settings.json`), then click **Sync Library** in the app.

### macOS / Linux
Not supported yet (the launch scripts are PowerShell for Windows).

## Notes
- The sync folder is **`src\Sync Library`**, inside the app's own folder. It starts empty and is not stored in GitHub, and neither are the database (`src\data`), model cache, or built `.exe` files; they are created on your computer.
- Full guide: `docs/APP_GUIDE.md`. Instructions for AI assistants: `src/LLM_INSTRUCTIONS.md`.
- Unit tests: on a Linux test run, 8 of 31 tests failed; the same tests failed on the original code, so this is not from the upload.
