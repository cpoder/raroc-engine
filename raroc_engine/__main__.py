"""Entry point for `python -m raroc_engine`.

Usage:
    python -m raroc_engine              # CLI mode (default)
    python -m raroc_engine.mcp_server   # MCP server mode
"""

from .cli import main

main()
