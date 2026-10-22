# RAG Knowledge Base

This is a separate local application built from the SearchPDFs extraction workflow. It indexes PDF, Word, Excel, CSV/TSV, and image files, preserves page previews, runs local OCR, detects tags and models, tracks revisions, and exposes exact source locations through MCP. It adds semantic retrieval using a local text embedding model and vector search. The connected LLM performs the final analysis and cites the source; this app does not run an LLM.

## Open and sync

Double-click **RAG Knowledge Base.exe**. The app uses `http://127.0.0.1:8766`, so it can run alongside SearchPDFs on port 8765. Click **Sync Library** to build its own index in this folder's `data` directory. The first sync of a large library will render and embed every page and can take a long time. Later syncs skip unchanged files without reopening them or recreating vectors.

`settings.json` points to the **`Sync Library` inside this application folder**.
The database paths were migrated to this internal copy without re-extracting,
OCRing, rendering, or embedding the existing collection. Add, replace, or
remove future source documents in this internal folder before syncing.

### Faster sync and optional GPU embedding

The sync writes PDF pages to SQLite in small transactions and reports time
spent on extraction, preview rendering, OCR, database writes, and embedding.
After a sync, expand **Sync timing** to see the slowest files and the actual
embedding device. Source files are never edited.

On a Windows PC with a supported NVIDIA GPU, run `setup_gpu.ps1` once. It
installs the optional CUDA runtime in `gpu-venv` inside this application
folder and verifies that the model actually uses CUDA. Close the
existing RAG app, then open **RAG Knowledge Base GPU.lnk** to use the same
database and Sync Library with GPU embeddings. **RAG Knowledge Base CPU.exe**
contains the same sync improvements for CPU use. With
`"embedding_device": "auto"`, new or changed documents use
CUDA when available and the CPU otherwise. Existing vectors need no rebuild.

The GPU accelerates embeddings; PDF extraction, rendering, OCR, and SQLite
writes still run on the CPU. **Sync timing** shows which stage limits each run.

## How retrieval works

- SQLite FTS5 and entity matching retain exact tags, model numbers, filenames, and engineering phrases.
- Text is divided into overlapping chunks of 220 words and embedded locally with `BAAI/bge-small-en-v1.5`.
- `sqlite-vec` stores 384-dimensional vectors in the app's own SQLite database.
- Hybrid search combines lexical and semantic ranks and spreads the first results across documents.
- Search results and analysis contexts include document names and exact PDF pages, Word sections, spreadsheet rows, or image frames. Use **Inspect source** or `get_source_page` for images and uncertain OCR.

The embedding model is cached in `models`. It has already been downloaded for this installation and runs without a network connection. The application does not use an OpenAI API key, paid embeddings, hosted vector database, or local LLM. It never sends source text to an embedding service.

The runtime components are colocated with the application: source documents in
`Sync Library`, the index and previews in `data`, embeddings in `models`, OCR in
`tools/tesseract`, the CPU development environment in `.venv`, the optional
CUDA environment in `gpu-venv`, and their base interpreter in
`python-runtime`. Moving the whole application folder preserves these relative
runtime relationships; update the absolute MCP configuration path if the
folder itself is moved.

## Connect an LLM

For a standalone guide to give an LLM, see **`LLM_INSTRUCTIONS.md`**. It explains which MCP tools to call and why the original documents, rather than `knowledge.db`, are the source of truth.

The separate MCP server is **RAG Knowledge Base MCP.exe**. This workspace's `.codex/config.toml` has been updated with the `rag_knowledge_base` server. Restart Codex to load it. The example configuration remains in `mcp_config.example.toml` if you use this app from another workspace. It exposes `search_knowledge_base` with `hybrid`, `lexical`, and `semantic` modes, plus `build_analysis_context`, `get_source_page`, `find_entity`, `list_pdf_documents`, and `get_document_outline`. The default for natural-language questions is hybrid search.

The new database starts empty. An LLM can query it after a sync has indexed documents. The original SearchPDFs MCP server remains separate.

## Command line and maintenance

The source implementation can run with `.venv`:

```powershell
.\.venv\Scripts\python.exe -m ragkb status
.\.venv\Scripts\python.exe -m ragkb index
.\.venv\Scripts\python.exe -m ragkb search "motor overload"
```

Run `setup.ps1` to recreate the environment and model cache, or `build_app.ps1` to rebuild the two executables. Run tests with `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.

The local model and vector store use [FastEmbed](https://qdrant.github.io/fastembed/Getting%20Started/) and [sqlite-vec](https://alexgarcia.xyz/sqlite-vec/python.html).
