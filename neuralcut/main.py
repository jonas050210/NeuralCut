"""NeuralCut entry point.

Starts the Python backend (FastAPI + uvicorn) and opens the frontend in the
default browser. Intended for local desktop use; no cloud connection is made.

Usage:
    python -m neuralcut               # start backend + open browser
    python -m neuralcut --port 9000   # custom port
    python -m neuralcut --no-browser  # headless (CI / service mode)

When packaged with Tauri (src-tauri/), the Rust shell starts this module as a
sidecar process and the webview loads http://127.0.0.1:<port>/.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from neuralcut.backend.app import get_app
from neuralcut.backend.di import Container
from neuralcut.config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neuralcut", description="NeuralCut backend")
    parser.add_argument("--host", default=None, help="Bind host (default: config/env)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: config/env)")
    parser.add_argument(
        "--config", default=None, help="Path to config.json (default: <data_dir>/config.json)"
    )
    parser.add_argument(
        "--data-dir", default=None, help="Application data directory"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the frontend browser tab"
    )
    args = parser.parse_args(argv)

    context = load_settings(config_file=args.config, data_dir=args.data_dir)
    host = args.host or context.settings.host
    port = args.port or context.settings.port

    app = get_app(Container(context))

    if not args.no_browser:
        # Open the browser once the server is up. uvicorn runs in the main
        # thread, so schedule the open after a short delay.
        import threading

        def _open() -> None:
            import time

            time.sleep(1.5)
            import webbrowser

            webbrowser.open(f"http://{host}:{port}/")

        threading.Thread(target=_open, daemon=True).start()

    print(f"NeuralCut {context.settings.version} — http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
