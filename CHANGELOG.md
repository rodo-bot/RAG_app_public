# Changelog

Newest changes at the top. Plain English, one line per change.

## 2026-10-26
- Fixed tagged builds so GitHub can automatically publish the completed macOS ZIP files as a Release.

## 2026-10-22
- Added native macOS setup and launch scripts, Apple silicon and Intel build automation, a writable Application Support location, and a compatible vector-search fallback for macOS Python builds that cannot load SQLite extensions.
- Updated the app with your cleaned-up version: stricter keyword search (fewer irrelevant pages), search falls back to keyword results if the meaning-based search fails, and new tests for both.
- The GPU setup, Python runtime and OCR tools now live inside the app folder instead of elsewhere on the computer.
- Added the RAG Knowledge Base app (code only; no database, sync documents, or built programs).
- The app now reads documents from its own `Sync Library` folder instead of a folder one level up.
- Created from app-template.
