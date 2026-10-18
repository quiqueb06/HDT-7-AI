"""Servidor MCP de Parachute S.A. con transporte Streamable HTTP.

Expone en un solo servidor todas las herramientas de los agentes (FAQs, clima
y agenda) definidas en `core/tools.py`, y deja un log por cada ejecucion.

Uso:
    python mcp_server.py        # escucha en http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from core.tools import mcp  # noqa: E402


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    mcp.run(
        "streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8001")),
    )


if __name__ == "__main__":
    main()
