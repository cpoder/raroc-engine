#!/usr/bin/env python3
"""Launch the RAROC Engine web application.

Usage:
    python3 serve.py              # http://localhost:8000
    python3 serve.py --port 3000  # custom port
"""

import argparse
from raroc_engine.web import run_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAROC Engine Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    args = parser.parse_args()

    print(f"\n  RAROC Engine starting at http://localhost:{args.port}\n")
    run_server(host=args.host, port=args.port)
