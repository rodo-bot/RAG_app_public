from __future__ import annotations

import os
import sys
import urllib.request
import webbrowser

from .web import run_web


APP_URL = "http://127.0.0.1:8766/"
STATUS_URL = "http://127.0.0.1:8766/api/status"


def _silence_missing_console_streams() -> None:
    """Give GUI builds safe output streams for libraries that expect them."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _already_running() -> bool:
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def main() -> int:
    _silence_missing_console_streams()
    if _already_running():
        webbrowser.open(APP_URL)
        return 0
    try:
        run_web(open_browser=True)
    except OSError as exc:
        # A second launch can race the first one while it is binding the port.
        if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in {48, 98, 10048}:
            webbrowser.open(APP_URL)
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
