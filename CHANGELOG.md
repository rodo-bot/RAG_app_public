# Changelog

Newest changes at the top. Plain English, one line per change.

## 2026-11-11
- Removed GitHub Actions. The automatic Windows/Mac builds no longer run on GitHub, so download links now come only from Releases you upload by hand (or run the app from source).

## 2026-11-07
- Added a single Prerequisites page (`docs/PREREQUISITES.md`) listing what you need for the Windows download, the Mac download, running from source, OCR, and connecting an AI assistant. It is linked from the README and included in each download.
- Reworded the AI instructions and the app guide so they no longer refer to one particular AI tool or to the author's own workspace, added a JSON example of how to register the MCP server, and corrected the note about when the search model is downloaded. The hint at the top of the app's search page now says "Analyze with your AI assistant" instead of naming one tool.
- Removed the `CLAUDE.md` file from the public copy so the AI instructions are not tied to one assistant; `AGENTS.md` (the tool-neutral name) stays, and the README now points to it.
- Added a ready-to-run Windows download (the app and the MCP server as `.exe` files in one ZIP). The automatic build now makes it for Windows and attaches it to each Release next to the Mac downloads, and the build is simply called "Build" now.
- The automatic build can now attach the Mac ZIP files to a Release that already exists, so a Release can be published from the GitHub website without the build failing.
- Clarified in the README that Windows needs Python installed and that there is no ready-made Windows download yet.
- Added an open-source MIT license so anyone can view, copy, download and reuse the code.
- Replaced example equipment tags and a drawing number in the tests and the search box hint with generic ones, and removed the author's personal email address from the project history.
- Tightened the automatic build so it can only publish a Release when a version tag is pushed; ordinary builds are now read-only.

## 2026-10-26
- Fixed tagged builds so GitHub can automatically publish the completed macOS ZIP files as a Release.

## 2026-10-22
- Added native macOS setup and launch scripts, Apple silicon and Intel build automation, a writable Application Support location, and a compatible vector-search fallback for macOS Python builds that cannot load SQLite extensions.
- Updated the app with your cleaned-up version: stricter keyword search (fewer irrelevant pages), search falls back to keyword results if the meaning-based search fails, and new tests for both.
- The GPU setup, Python runtime and OCR tools now live inside the app folder instead of elsewhere on the computer.
- Added the RAG Knowledge Base app (code only; no database, sync documents, or built programs).
- The app now reads documents from its own `Sync Library` folder instead of a folder one level up.
- Created from app-template.
