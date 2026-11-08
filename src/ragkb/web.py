from __future__ import annotations

import json
import mimetypes
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .indexer import index_library
from .ocr import find_tesseract
from .paths import APP_ROOT, DATA_DIR, SYNC_LIBRARY_DIR
from .rag_search import RAGSearch
from .rag_store import RAGDB


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.value: dict[str, Any] = {
            "running": False,
            "message": "Ready",
            "progress": None,
            "last_report": None,
            "ocr_available": find_tesseract() is not None,
        }
        self._stats_cache: dict[str, int] | None = None
        self._stats_at = 0.0

    def update(self, **values: Any) -> None:
        with self.lock:
            self.value.update(values)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.value)

    def stats(self, db: RAGDB) -> dict[str, int]:
        with self.lock:
            if self.value["running"] and self._stats_cache is not None and time.monotonic() - self._stats_at < 15:
                return self._stats_cache
        result = db.stats()
        with self.lock:
            self._stats_cache = result
            self._stats_at = time.monotonic()
        return result


STATE = RuntimeState()


def _start_index_job(force: bool = False) -> bool:
    with STATE.lock:
        if STATE.value["running"]:
            return False
        STATE.value.update(running=True, message="Scanning the document library...", progress=None)

    def progress(event: dict) -> None:
        if event.get("event") == "embedding":
            message = f"Embedding {event['document']} - page {event['page']} of {event['page_count']}"
        elif event.get("event") == "page":
            location = event.get("source_label") or f"page {event['page']} of {event['page_count']}"
            message = f"Indexing {event['document']} - {location}"
        elif event.get("event") == "scan":
            message = f"Found {event['total_files']} library files to check"
        elif event.get("event") == "file_complete":
            message = f"Checked {event['completed_files']} of {event['total_files']} files"
        elif event.get("event") == "removed":
            message = f"Removing {event.get('document', 'missing document')} from the index"
        else:
            message = f"Opening {event.get('document', 'document')}"
        STATE.update(message=message, progress=event)

    def run() -> None:
        try:
            report = index_library(SYNC_LIBRARY_DIR, db=RAGDB(), force=force, enable_ocr=True, progress=progress)
            STATE.update(
                running=False,
                message=(
                    f"Finished: {report.indexed} indexed, {report.relocated} moved, "
                    f"{report.skipped} unchanged, {report.embedded_documents} embedded, "
                    f"{report.removed} removed, {report.failed} failed"
                ),
                last_report=report.as_dict(),
                progress={
                    "event": "finished", "total_files": report.discovered,
                    "completed_files": report.discovered,
                },
                ocr_available=find_tesseract() is not None,
            )
        except Exception as exc:
            STATE.update(running=False, message=f"Indexing failed: {type(exc).__name__}: {exc}", progress=None)

    threading.Thread(target=run, name="searchpdfs-indexer", daemon=True).start()
    return True


class SearchPDFHandler(BaseHTTPRequestHandler):
    server_version = "RAGKnowledgeBase/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def searcher(self) -> KnowledgeSearch:
        return self.server.searcher  # type: ignore[attr-defined]

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            self._text(INDEX_HTML)
            return
        if parsed.path == "/app.css":
            self._text(APP_CSS, "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._text(APP_JS, "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/status":
            payload = STATE.snapshot()
            payload["stats"] = STATE.stats(self.searcher.db)
            payload["source_library"] = str(SYNC_LIBRARY_DIR)
            self._json(payload)
            return
        if parsed.path == "/api/documents":
            self._json(self.searcher.list_documents())
            return
        if parsed.path == "/api/search":
            value = query.get("q", [""])[0]
            page_type = query.get("page_type", [None])[0]
            limit = int(query.get("limit", ["30"])[0])
            mode = query.get("mode", ["hybrid"])[0]
            self._json(self.searcher.search(value, limit=limit, page_type=page_type or None, mode=mode))
            return
        if parsed.path.startswith("/api/document/"):
            try:
                document_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._json({"error": "Invalid document ID"}, 400)
                return
            document = self.searcher.get_document(document_id)
            self._json(document if document else {"error": "Not found"}, 200 if document else 404)
            return
        if parsed.path.startswith("/api/page/"):
            try:
                page_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._json({"error": "Invalid page ID"}, 400)
                return
            page = self.searcher.get_page(page_id)
            self._json(page if page else {"error": "Not found"}, 200 if page else 404)
            return
        if parsed.path == "/asset":
            self._serve_asset(query.get("path", [""])[0])
            return
        self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/index":
            query = urllib.parse.parse_qs(parsed.query)
            force = query.get("force", ["false"])[0].lower() == "true"
            started = _start_index_job(force=force)
            self._json({"started": started, **STATE.snapshot()}, 202 if started else 409)
            return
        self._json({"error": "Not found"}, 404)

    def _serve_asset(self, requested: str) -> None:
        if not requested:
            self._json({"error": "Missing path"}, 400)
            return
        candidate = (APP_ROOT / requested).resolve()
        data_root = DATA_DIR.resolve()
        if data_root != candidate and data_root not in candidate.parents:
            self._json({"error": "Invalid asset path"}, 403)
            return
        if not candidate.is_file():
            self._json({"error": "Asset not found"}, 404)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        with candidate.open("rb") as stream:
            while block := stream.read(1024 * 256):
                self.wfile.write(block)


class SearchPDFServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        super().__init__(address, SearchPDFHandler)
        self.searcher = RAGSearch(RAGDB())


def run_web(host: str = "127.0.0.1", port: int = 8766, open_browser: bool = False) -> None:
    server = SearchPDFServer((host, port))
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if sys.stdout is not None:
        print(f"RAG Knowledge Base is running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RAG Knowledge Base</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark">R</span><div><strong>RAG Knowledge Base</strong><small>Local hybrid retrieval</small></div></div>
    <nav>
      <button class="nav active" data-view="search"><span>⌕</span> Search</button>
      <button class="nav" data-view="library"><span>▤</span> Library</button>
    </nav>
    <div class="privacy"><span class="privacy-dot"></span><div><strong>Local-only mode</strong><small>No API key. No paid calls.</small></div></div>
  </aside>
  <main>
    <header>
      <div><p class="eyebrow">Engineering document intelligence</p><h1 id="viewTitle">Search your knowledge base</h1></div>
      <button id="indexButton" class="primary">Sync Library</button>
    </header>
    <section id="statusBar" class="status hidden" role="status" aria-live="polite">
      <div class="status-line"><span class="spinner" id="syncSpinner"></span><span id="statusText"></span></div>
      <div class="sync-progress"><progress id="syncProgress" max="100"></progress><span id="syncProgressLabel">Finding files...</span></div>
      <details id="syncDetails" class="hidden"><summary>Sync timing</summary><div id="syncTiming"></div></details>
    </section>
    <section class="stats" id="stats"></section>
    <section id="searchView">
      <div class="llm-note"><strong>Sync here. Analyze with your AI assistant.</strong><span>Documents are indexed locally with exact text and semantic vectors. The LLM reads source evidence through this app's MCP tools.</span></div>
      <form id="searchForm" class="search-box">
        <span class="search-icon">⌕</span>
        <input id="query" autocomplete="off" placeholder="Try: PUMP 1 PHASE FAIL, LIT 0101, RedLion, tank level...">
        <select id="searchMode" aria-label="Retrieval mode"><option value="hybrid">Hybrid</option><option value="lexical">Exact text</option><option value="semantic">Semantic</option></select>
        <button>Search</button>
      </form>
      <div class="section-heading"><div><h2>Evidence</h2><p id="resultSummary">Search exact tags, phrases, models, and drawing notes.</p></div></div>
      <div id="results" class="results empty-state"><div class="empty-icon">⌕</div><h3>Search across every indexed source</h3><p>Results retain the original file, exact page/sheet/section location, confidence, and visual evidence.</p></div>
    </section>
    <section id="libraryView" class="hidden">
      <div class="section-heading"><div><h2>Document library</h2><p id="sourceLibrary">Loading source folder...</p></div></div>
      <div id="documents" class="documents"></div>
    </section>
  </main>
  <dialog id="pageDialog"><button class="dialog-close" aria-label="Close">×</button><div id="pageDetail"></div></dialog>
  <script src="/app.js"></script>
</body>
</html>'''


APP_CSS = r''':root{--ink:#13243a;--muted:#66758a;--line:#dce3eb;--bg:#f4f7fa;--panel:#fff;--blue:#1670d2;--blue2:#0d4f99;--nav:#101f33;--green:#27a36a;--shadow:0 10px 30px rgba(21,41,68,.08)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Segoe UI",Arial,sans-serif}.sidebar{position:fixed;inset:0 auto 0 0;width:250px;background:linear-gradient(180deg,#10223a,#0d192a);color:white;padding:28px 18px;display:flex;flex-direction:column}.brand{display:flex;align-items:center;gap:12px;padding:0 8px 28px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,#3aa0ff,#1262c1);font-weight:800;font-size:20px}.brand strong,.brand small{display:block}.brand strong{font-size:17px}.brand small{color:#9fb1c8;font-size:11px;margin-top:1px}.sidebar nav{display:grid;gap:6px}.nav{border:0;background:transparent;color:#b8c5d6;padding:11px 13px;text-align:left;border-radius:9px;font-weight:600;cursor:pointer}.nav span{display:inline-block;width:26px;font-size:19px;vertical-align:-1px}.nav:hover,.nav.active{background:#1a3455;color:#fff}.privacy{margin-top:auto;border:1px solid #29435f;background:#132943;border-radius:12px;padding:12px;display:flex;gap:10px;align-items:flex-start}.privacy-dot{width:9px;height:9px;border-radius:50%;background:#48d692;box-shadow:0 0 0 4px rgba(72,214,146,.12);margin-top:5px}.privacy strong,.privacy small{display:block}.privacy strong{font-size:12px}.privacy small{color:#9fb1c8;font-size:10px;margin-top:2px}main{margin-left:250px;padding:36px 42px;min-height:100vh;max-width:1600px}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}.eyebrow{margin:0 0 3px;color:var(--blue);font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.12em}h1{font-size:27px;margin:0;letter-spacing:-.02em}h2{font-size:18px;margin:0}button{font:inherit}.primary,.search-box button{border:0;background:linear-gradient(135deg,var(--blue),var(--blue2));color:white;padding:11px 17px;border-radius:9px;font-weight:700;cursor:pointer;box-shadow:0 5px 14px rgba(22,112,210,.2)}.primary:disabled{opacity:.6;cursor:wait}.status{display:flex;gap:10px;align-items:center;background:#e8f3ff;border:1px solid #bfdcff;color:#145592;border-radius:10px;padding:11px 14px;margin-bottom:18px}.spinner{width:15px;height:15px;border:2px solid #8fc2f2;border-top-color:#176ec3;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.stats{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:14px;margin-bottom:18px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:var(--shadow)}.stat strong{display:block;font-size:24px;letter-spacing:-.03em}.stat span{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.llm-note{display:flex;gap:10px;align-items:baseline;background:#e8f3ff;border:1px solid #bfdcff;color:#294d72;border-radius:10px;padding:11px 14px;margin-bottom:14px}.llm-note strong{color:#145592;white-space:nowrap}.llm-note span{font-size:12px}.search-box{height:62px;background:var(--panel);border:1px solid #cfd9e5;border-radius:13px;display:flex;align-items:center;padding:7px 8px 7px 18px;box-shadow:var(--shadow);margin-bottom:28px}.search-icon{font-size:26px;color:#7990aa;margin-right:10px}.search-box input{flex:1;border:0;outline:0;font-size:16px;color:var(--ink);min-width:0}.search-box button{padding:12px 23px}.section-heading{display:flex;align-items:end;justify-content:space-between;margin:0 0 14px}.section-heading p{margin:3px 0 0;color:var(--muted);font-size:12px}.results{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}.result{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:grid;grid-template-columns:126px 1fr;min-height:174px;box-shadow:0 3px 12px rgba(21,41,68,.04);transition:.15s}.result:hover{transform:translateY(-2px);box-shadow:var(--shadow);border-color:#b8cce1}.thumb{width:126px;height:100%;object-fit:contain;background:#e8edf3;padding:6px}.result-body{padding:14px;min-width:0}.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.badge{font-size:9px;text-transform:uppercase;letter-spacing:.06em;font-weight:800;color:#38658f;background:#e8f3fb;padding:3px 6px;border-radius:5px}.badge.entity{color:#7a4a06;background:#fff1cf}.result h3{font-size:14px;margin:0 0 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{font-size:11px;color:var(--muted);margin-bottom:8px}.snippet{font-size:11px;color:#44546a;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.result button,.document button{border:0;background:transparent;color:var(--blue);font-weight:700;padding:8px 0 0;cursor:pointer;font-size:11px}.empty-state{display:grid;place-items:center;text-align:center;background:var(--panel);border:1px dashed #bcc8d6;border-radius:13px;padding:50px 20px;color:var(--muted)}.empty-state h3{color:var(--ink);margin:8px 0 3px}.empty-state p{max-width:520px;margin:0}.empty-icon{font-size:40px;color:#8da2b9}.documents{display:grid;gap:10px}.document{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}.document h3{font-size:14px;margin:0 0 4px}.document p{font-size:11px;color:var(--muted);margin:0}.document .status-pill{color:#16724c;background:#e3f7ed;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:800;text-transform:uppercase}.hidden{display:none!important}dialog{width:min(1120px,94vw);height:min(830px,92vh);border:0;border-radius:15px;padding:0;box-shadow:0 30px 90px rgba(0,0,0,.28)}dialog::backdrop{background:rgba(8,20,34,.72);backdrop-filter:blur(3px)}.dialog-close{position:absolute;right:12px;top:10px;z-index:3;width:36px;height:36px;border:0;border-radius:50%;background:#12253d;color:white;font-size:25px;cursor:pointer}#pageDetail{height:100%}.page-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,.75fr);height:100%}.page-image{background:#dfe5eb;display:grid;place-items:center;overflow:auto;padding:22px}.page-image img{max-width:100%;max-height:100%;object-fit:contain;box-shadow:0 4px 18px rgba(0,0,0,.18);background:white}.page-info{padding:28px;overflow:auto}.page-info h2{font-size:20px;padding-right:28px}.page-info .meta{margin:6px 0 18px}.page-info h4{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:20px 0 7px}.page-info pre{white-space:pre-wrap;font:12px/1.5 "Segoe UI",sans-serif;color:#34465c;margin:0}.entity-list{display:flex;gap:5px;flex-wrap:wrap}.entity-chip{font-size:10px;background:#eef3f7;border:1px solid #d6e0e8;padding:4px 7px;border-radius:6px}@media(max-width:850px){.sidebar{position:static;width:auto;height:auto;flex-direction:row;align-items:center;padding:14px}.sidebar nav{display:flex}.privacy{display:none}.brand{padding:0;margin-right:auto}.brand small{display:none}main{margin:0;padding:22px}.stats{grid-template-columns:repeat(2,1fr)}.llm-note{display:block}.llm-note strong,.llm-note span{display:block}.page-layout{grid-template-columns:1fr}.page-info{max-height:42vh}.results{grid-template-columns:1fr}}'''


APP_CSS += r'''.status{display:block}.status-line{display:flex;gap:10px;align-items:center}.sync-progress{display:flex;gap:12px;align-items:center;margin-top:10px}.sync-progress progress{flex:1;min-width:0;height:13px;accent-color:var(--blue)}.sync-progress span{font-size:11px;white-space:nowrap;color:#145592;min-width:135px;text-align:right}.status details{margin-top:10px;font-size:11px}.status summary{cursor:pointer;font-weight:700}.status #syncTiming{margin-top:6px;line-height:1.6}.search-box select{border:1px solid #cfd9e5;border-radius:7px;background:#fff;color:var(--ink);padding:9px;margin-right:8px}@media(max-width:600px){.sync-progress{display:block}.sync-progress span{display:block;text-align:left;margin-top:4px}.sync-progress progress{width:100%}}'''

APP_JS = r'''const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const asset=p=>`/asset?path=${encodeURIComponent(p)}`;let poll;
async function json(url,options){const r=await fetch(url,options);return r.json()}
function renderStats(s){const items=[[s.documents,"Documents"],[s.pages,"Source locations"],[s.embedded_documents,"Embedded documents"],[s.rag_chunks,"RAG chunks"],[s.image_documents,"Images"],[s.entities,"Detected entities"]];$("#stats").innerHTML=items.map(x=>`<div class="stat"><strong>${x[0]}</strong><span>${x[1]}</span></div>`).join("")}
function renderSyncProgress(s){const bar=$("#syncProgress"),label=$("#syncProgressLabel");if(!s.running&&s.last_report){bar.value=100;const n=s.last_report.discovered;label.textContent=`${n} of ${n} files checked (100%)`;return}const p=s.progress||{},total=Number(p.total_files);if(!Number.isFinite(total)||total<=0){bar.removeAttribute("value");label.textContent="Finding files...";return}const done=Number(p.completed_files||0),pageFraction=p.page_count?Math.min(1,Math.max(0,(Number(p.page)-1)/Number(p.page_count))):0;const fraction=p.event==="page"?0.75*pageFraction:p.event==="embedding"?0.75+0.25*pageFraction:0;const percent=Math.min(99,Math.floor(100*(done+fraction)/total));bar.value=percent;label.textContent=done>=total?`Finishing ${total} files...`:`${done} of ${total} files checked (${percent}%)`}
function renderSyncTiming(s){const details=$("#syncDetails"),report=s.last_report;details.classList.toggle("hidden",s.running||!report);if(!report||s.running)return;const t=report.timings_seconds||{},fmt=x=>`${Number(x||0).toFixed(1)} s`;const parts=[["Total",t.sync_total],["Index",t.index_total],["Text",t.text_extraction],["Render/previews",t.render_and_preview],["OCR",t.ocr],["Database writes",t.database_write],["Embedding",t.embedding_total],["Model",t.embedding_inference],["Vector writes",t.vector_write]].map(([name,value])=>`${name}: ${fmt(value)}`);const slow=(report.slow_files||[]).slice(0,3).map(x=>`${esc(x.document)} (${fmt(x.seconds)})`);$("#syncTiming").innerHTML=`<div>${parts.join(" · ")}</div><div>Embedding device: ${esc(report.embedding_backend||"not used")}</div>${slow.length?`<div>Slowest files: ${slow.join(", ")}</div>`:""}`}
async function refreshStatus(){const s=await json("/api/status");renderStats(s.stats);$("#sourceLibrary").textContent=`Read-only source: ${s.source_library}`;$("#indexButton").disabled=s.running;$("#indexButton").textContent=s.running?"Syncing...":"Sync Library";$("#statusBar").classList.toggle("hidden",!s.running&&!s.last_report&&s.message==="Ready");$("#syncSpinner").classList.toggle("hidden",!s.running);$("#statusText").textContent=s.message;renderSyncProgress(s);renderSyncTiming(s);if(s.running&&!poll)poll=setInterval(refreshStatus,900);if(!s.running&&poll){clearInterval(poll);poll=null;loadDocuments()}}
async function startIndex(){await json("/api/index",{method:"POST"});await refreshStatus()}
async function search(e){e?.preventDefault();const q=$("#query").value.trim();if(!q)return;$("#results").className="results";$("#results").innerHTML='<div class="empty-state"><span class="spinner"></span><p>Searching local evidence...</p></div>';const mode=$("#searchMode").value;const rows=await json(`/api/search?q=${encodeURIComponent(q)}&mode=${encodeURIComponent(mode)}`);$("#resultSummary").textContent=`${rows.length} source${rows.length===1?"":"s"} matched “${q}”`;if(!rows.length){$("#results").className="results empty-state";$("#results").innerHTML='<div class="empty-icon">∅</div><h3>No indexed evidence found</h3><p>Try a shorter phrase, an equipment tag, or sync again after enabling local OCR.</p>';return}$("#results").innerHTML=rows.map(r=>`<article class="result"><img class="thumb" src="${asset(r.thumbnail_path)}" alt="${esc(r.source_label)}"><div class="result-body"><div class="badges"><span class="badge">${esc(r.file_type)}</span><span class="badge">${esc(r.page_type.replaceAll("_"," "))}</span>${r.matched_entity?`<span class="badge entity">Exact: ${esc(r.matched_entity)}</span>`:""}</div><h3>${esc(r.document_name)}</h3><div class="meta">${esc(r.source_label)} · ${esc(r.text_source)} · ${Math.round(r.confidence*100)}% confidence</div><div class="snippet">${esc(r.snippet)}</div><button onclick="showPage(${r.page_id})">Inspect source →</button></div></article>`).join("")}
async function loadDocuments(){const docs=await json("/api/documents");$("#documents").innerHTML=docs.length?docs.map(d=>`<article class="document"><div><h3>${esc(d.relative_path||d.name)}</h3><p>${esc(d.file_type)} · ${d.page_count} source location${d.page_count===1?"":"s"} · ${esc(d.revision_label||"Unversioned")} · indexed ${esc(d.indexed_at||"not yet")}</p><button onclick="showDocument(${d.id})">Browse evidence →</button></div><span class="status-pill">${d.is_current?"current":"superseded"}</span></article>`).join(""):'<div class="empty-state"><h3>No indexed documents</h3><p>Click “Sync Library” to index the configured source folder shown above.</p></div>'}
async function showDocument(id){const d=await json(`/api/document/${id}`);switchView("library");$("#documents").innerHTML=`<div class="section-heading"><div><h2>${esc(d.name)}</h2><p>${d.page_count} source location${d.page_count===1?"":"s"}</p></div><button class="primary" onclick="loadDocuments()">Back to library</button></div><div class="results">${d.pages.map(p=>`<article class="result"><img class="thumb" src="${asset(p.thumbnail_path)}"><div class="result-body"><div class="badges"><span class="badge">${esc(p.page_type.replaceAll("_"," "))}</span></div><h3>${esc(p.source_label||`Page ${p.page_number}`)}</h3><div class="meta">${esc(p.text_source)} · ${p.word_count} words · ${Math.round(p.confidence*100)}% confidence</div><button onclick="showPage(${p.id})">Inspect source →</button></div></article>`).join("")}</div>`}
async function showPage(id){const p=await json(`/api/page/${id}`);const entities=p.entities||[];$("#pageDetail").innerHTML=`<div class="page-layout"><div class="page-image"><img src="${asset(p.preview_path)}" alt="${esc(p.document_name)} ${esc(p.source_label)}"></div><div class="page-info"><h2>${esc(p.document_name)}</h2><div class="meta">${esc(p.source_label||`Page ${p.page_number}`)} · ${esc(p.page_type.replaceAll("_"," "))} · ${esc(p.text_source)} · ${Math.round(p.confidence*100)}% confidence</div><h4>Detected entities</h4><div class="entity-list">${entities.length?entities.map(e=>`<span class="entity-chip">${esc(e.display_value)}</span>`).join(""):"<span class=meta>None detected</span>"}</div><h4>Extracted evidence</h4><pre>${esc(p.search_text||"No searchable text was extracted. The source preview is retained for visual review.")}</pre></div></div>`;$("#pageDialog").showModal()}
function switchView(view){const search=view==="search";$("#searchView").classList.toggle("hidden",!search);$("#libraryView").classList.toggle("hidden",search);$("#viewTitle").textContent=search?"Search your knowledge base":"Indexed document library";document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.view===view));if(!search)loadDocuments()}
$("#searchForm").addEventListener("submit",search);$("#indexButton").addEventListener("click",startIndex);document.querySelectorAll(".nav").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.view)));$(".dialog-close").addEventListener("click",()=>$("#pageDialog").close());$("#pageDialog").addEventListener("click",e=>{if(e.target===$("#pageDialog"))e.target.close()});refreshStatus();loadDocuments();'''


if __name__ == "__main__":
    run_web(open_browser=True)
