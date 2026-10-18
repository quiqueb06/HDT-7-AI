"""Conexion de los agentes al servidor MCP de herramientas.

Todos los agentes comparten una sola conexion Streamable HTTP al servidor MCP
(`mcp_server.py`). Un filtro dinamico hace que cada agente vea solo las
herramientas de su especialidad, igual que cuando las recibia directamente.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List

from agents.mcp import MCPServerStreamableHttp, ToolFilterContext

#: Herramientas del servidor MCP que puede usar cada agente (por nombre del agente).
HERRAMIENTAS_POR_AGENTE: Dict[str, List[str]] = {}


def permitir(nombre_agente: str, herramientas: Iterable[str]) -> None:
    """Registra las herramientas MCP que puede ver un agente."""

    HERRAMIENTAS_POR_AGENTE[nombre_agente] = list(herramientas)


def _filtrar(contexto: ToolFilterContext, herramienta) -> bool:
    return herramienta.name in HERRAMIENTAS_POR_AGENTE.get(contexto.agent.name, [])


def crear_servidor_mcp() -> MCPServerStreamableHttp:
    """Cliente MCP hacia el servidor de herramientas de Parachute S.A."""

    return MCPServerStreamableHttp(
        name="Parachute S.A.",
        params={"url": os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")},
        tool_filter=_filtrar,
        client_session_timeout_seconds=60,
    )
