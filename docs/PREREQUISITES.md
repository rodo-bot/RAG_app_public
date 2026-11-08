# Prerequisites

What you need before installing or using the RAG Knowledge Base.

## For everyone

- A computer running 64-bit Windows, or macOS (Apple silicon or Intel). Linux is not supported yet.
- An internet connection the first time you sync or search. The app downloads a small search model once, keeps it next to the app, and works offline afterwards. Until the model has downloaded, the meaning-based search cannot work.
- Free disk space for the app (the downloads are about 110 to 120 MB), the search model, and the index and page previews built from your documents.
- Documents the app can read: PDF, Word, Excel, CSV/TSV, and image files.
- To have an AI assistant answer questions from your documents: an AI tool that can use MCP servers (local "stdio" ones) and that runs on the same computer, because it has to launch a program from this folder. The app does not include an AI, and it needs no API keys or paid services of its own. The AI tool you choose may have its own account or cost. See `src/LLM_INSTRUCTIONS.md`.

## Windows download (the ZIP from Releases)

- Nothing else to install. You do not need Python.
- Unzip to a folder you can write to, such as Documents. The app keeps its data next to the `.exe`, so avoid `Program Files`.
- Windows may show "Windows protected your PC" because the build is not signed with a paid certificate. Click **More info**, then **Run anyway**.

## macOS download (the ZIP from Releases)

- Nothing else to install. You do not need Python.
- Pick the ZIP that matches your Mac: `arm64` for Apple silicon (M1 or newer), `x86_64` for Intel. Apple menu, then About This Mac, shows which you have.
- The automatic build runs on macOS 15. Older macOS versions have not been tested.
- The first launch needs Control-click, then **Open**, because the app is not notarized with a paid Apple certificate.
- The app keeps its data in `~/Library/Application Support/RAG Knowledge Base`.

## Running from the source code

- Python 3.11 or newer, available as `python` (Windows) or `python3` (macOS). The automated tests use Python 3.12. On Windows, tick "Add python.exe to PATH" in the Python installer.
- An internet connection to install the Python packages listed in `src/requirements.txt` and to download the search model.
- Windows: PowerShell. If Windows says running scripts is disabled, start a script like this instead: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.
- macOS: Terminal. The steps are in the README.
- Optional, Windows only: a supported NVIDIA graphics card for faster indexing. `setup_gpu.ps1` sets it up and checks it. If the GPU cannot be used, the normal app is unchanged.

## Optional: reading scanned pages and pictures (OCR)

- Install Tesseract. On Windows, use the build linked from https://github.com/UB-Mannheim/tesseract/wiki; the app looks for it on your PATH, in `C:\Program Files\Tesseract-OCR`, or in `tools\tesseract` next to the app. On macOS, install [Homebrew](https://brew.sh) and run `brew install tesseract`.
- Without Tesseract, the app still indexes documents that contain real text, but it cannot read text that exists only as a picture.
