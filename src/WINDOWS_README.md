# RAG Knowledge Base for Windows

1. Unzip this download to a folder you can write to, for example your
   Documents folder. Keep the files together: the app stores its data next to
   the `.exe`.
2. Double-click `RAG Knowledge Base.exe`. Windows may show "Windows protected
   your PC" because the GitHub build is not signed with a paid certificate.
   Click **More info**, then **Run anyway**. Some antivirus programs also
   flag this kind of packaged app by mistake; the full source code is in the
   repository if you want to check it.
3. Put the documents you want searchable in the `Sync Library` folder next to
   the app (it is created the first time you open the app). Then click
   **Sync Library** in the app.

The database, previews, downloaded search model, settings, and your documents
all stay in this folder. They are created while you use the app and are not
included in the download. The first time you sync or search, the app
downloads a small search model, so you need an internet connection once.

`RAG Knowledge Base MCP.exe` is the standalone MCP server. Configure an MCP
client to run that file by its full path. `LLM_INSTRUCTIONS.md` explains how an
AI assistant should use it.

Optional OCR (reading scanned pages and images) needs Tesseract. Install it
from https://github.com/UB-Mannheim/tesseract/wiki.

`PREREQUISITES.md` in this folder lists everything you need.
