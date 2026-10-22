# RAG Knowledge Base LLM workflow

This folder is a separate local RAG application with its own SQLite evidence and vector index. `settings.json` selects the read-only source library (default: the `Sync Library` folder in this app's folder); `data` and `models` belong to this app.

Read `LLM_INSTRUCTIONS.md` for the complete retrieval and citation workflow when the user asks you to use this RAG knowledge base.

When answering questions about this indexed collection, use the `rag_knowledge_base` MCP server's tools. Start broad questions with `build_analysis_context`; use `search_knowledge_base` for focused queries and `get_source_page` to inspect full evidence and images. Use `version_scope="all"` for revision comparisons. Search results are evidence for the LLM to interpret, compare, and summarize, not finished answers. Cite the filename and exact PDF page, Word section, spreadsheet sheet and rows, or image frame.

Do not modify original documents in the selected Sync Library unless explicitly requested. Save generated deliverables in this folder's `Output` directory. Do not use a paid embedding service, hosted vector database, OpenAI API key, or local LLM for indexing or final answers.
