# Changelog

Newest changes at the top. Plain English, one line per change.

## 2026-11-07
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
