# How an LLM should use RAG Knowledge Base

Read this file when the user asks you to answer from the **RAG Knowledge Base**. These are retrieval instructions, not evidence about any product or document. **You must use the `rag_knowledge_base` MCP tools to answer collection questions.**

## Which knowledge base to use

- Use the MCP server named **`rag_knowledge_base`**. It is separate from the original **`searchpdfs`** server. When the user requests RAG Knowledge Base, direct your searches to `rag_knowledge_base`, not `searchpdfs` or raw SQLite queries.
- The MCP server is the program `RAG Knowledge Base MCP.exe` (Windows) or `RAG Knowledge Base MCP` (macOS) in the app folder. The user's MCP client must be configured to launch it; see "Connecting a new LLM client" below.
- The app reads the `Sync Library` folder inside this RAG application folder, including its subfolders. `settings.json` defines that active source folder.
- This app stores its **own** index in `data/knowledge.db`. The original SearchPDFs database is separate. Each app must be synced separately.

## Connecting a new LLM client

Reading this folder does not itself create an MCP connection. **Before answering, check whether the `rag_knowledge_base` MCP tools are available.** If they are not, attempt to connect the server when your client supports local STDIO MCP servers and you have access to its configuration. Register the MCP program as `rag_knowledge_base`, using its full file path. Most MCP clients accept a JSON entry like this (exact file and key names vary by client, and on macOS the command is the path to `RAG Knowledge Base MCP`):

```json
{
  "mcpServers": {
    "rag_knowledge_base": {
      "command": "C:\\path\\to\\RAG Knowledge Base MCP.exe",
      "args": []
    }
  }
}
```

`mcp_config.example.toml` in the repository shows the same settings in TOML for clients that use that format. Reload or restart the client if required, then verify the tools are available by calling one.

**If you cannot connect, tell the user clearly that you could not access the RAG Knowledge Base, why if known, and what setup is needed. Do not pretend to have searched it, use the original `searchpdfs` server as a silent substitute, or query `knowledge.db` directly as a workaround.** A remote client without access to this computer cannot launch the local executable just because it can read this file.

## What is the source of truth?

**The original source documents are the authority.** `data/knowledge.db` is a searchable snapshot of extracted text, metadata, OCR, and semantic vectors. It can be incomplete or stale until the RAG app finishes syncing, and OCR can be wrong. Do not treat a vector match or an extracted snippet as a verified fact without checking its source location when the detail matters.

Use the MCP tools to retrieve evidence instead of opening or querying `knowledge.db` directly. The database is an implementation detail, not the interface for answering collection questions. Do not edit the database or original source files while answering a question.

## Retrieval workflow

1. For a broad question, call **`build_analysis_context`** with the user's question. For a focused question, call **`search_knowledge_base`**. Its default `mode="hybrid"` combines exact text and semantic search.
2. For equipment tags, model numbers, drawing numbers, or exact phrases, also try **`find_entity`** or `search_knowledge_base` with `mode="lexical"`. Semantic similarity alone is not reliable for exact identifiers.
3. For a whole-document summary, call **`list_pdf_documents`** (despite its legacy name, it lists all supported file types), then **`get_document_outline`**, then inspect the relevant locations.
4. Use **`get_source_page`** with `include_image=true` for diagrams, drawings, markups, tables, spreadsheet layouts, images, or uncertain OCR. Read the visual source rather than relying only on extracted text.
5. Normal searches use the current recognized revision. For older issues, revisions, or change comparisons, set `version_scope="all"` and identify which revision supports each claim.
6. If the first search is weak, retry with exact model numbers, tags, synonyms, and shorter technical phrases. If the index is still syncing or the document is not yet indexed, say so rather than conclude that the source contains nothing.

## How to answer

You perform the interpretation, comparison, calculations, recommendations, and summary. The retrieval tools only provide evidence. Cite the filename and exact PDF page, Word section, spreadsheet sheet and row range, or image frame for material claims. Clearly separate what the source says from your inference. When the retrieved evidence is insufficient, say what is missing.

## Example request from the user

> Read `RAG Knowledge base/LLM_INSTRUCTIONS.md`. Use the `rag_knowledge_base` MCP tools to answer this question from the indexed documents, inspect source pages where needed, and cite exact locations: [your question]
