# RAG Knowledge Base for macOS

1. Move `RAG Knowledge Base.app` to Applications.
2. Control-click the app, choose **Open**, and confirm the first launch. The
   GitHub build is ad-hoc signed but not notarized with a paid Apple Developer
   certificate.
3. Add documents to
   `~/Library/Application Support/RAG Knowledge Base/Sync Library`.
4. Open the app and click **Sync Library**.

The database, previews, downloaded embedding model, settings, and source
documents stay in `~/Library/Application Support/RAG Knowledge Base`. They are
created at runtime and are not included in this download.

`RAG Knowledge Base MCP` is the standalone MCP server. Configure an MCP client
to run that absolute file path. macOS may require the same Control-click/Open
approval the first time it is used.

Optional OCR requires Tesseract. With Homebrew installed, run:

```bash
brew install tesseract
```
