"""Fabricas de agentes especialistas.

Cada funcion construye un `Agent` del SDK de OpenAI Agents con el prompt que
le corresponde a ese rol. Las herramientas las toma del servidor MCP
(`servidor_mcp`); `core.mcp_client` filtra cuales puede ver cada agente.

Los parametros `extra_instructions` y `handoffs` permiten adaptar un agente a
una arquitectura sin duplicar su logica ni su prompt base.
"""

from __future__ import annotations

from typing import Optional, Sequence

from agents import Agent
from agents.mcp import MCPServer

from . import mcp_client, prompts, tools
from .config import DEFAULT_MODEL


def _instructions(base: str, extra: Optional[str], prefix: Optional[str] = None) -> str:
    partes = [p for p in (prefix, base, extra) if p]
    return "\n\n".join(partes)


def make_faq_agent(
    servidor_mcp: MCPServer,
    extra_instructions: Optional[str] = None,
    handoffs: Optional[Sequence[Agent]] = None,
    prompt_prefix: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    name: str = "Agente FAQ",
) -> Agent:
    """Especialista en la base de conocimientos (preguntas frecuentes)."""

    mcp_client.permitir(name, tools.FAQ_TOOLS)
    return Agent(
        name=name,
        handoff_description="Responde preguntas sobre precios, requisitos, logistica y politicas de Parachute S.A.",
        instructions=_instructions(prompts.FAQ_AGENT, extra_instructions, prompt_prefix),
        mcp_servers=[servidor_mcp],
        handoffs=list(handoffs or []),
        model=model,
    )


def make_weather_agent(
    servidor_mcp: MCPServer,
    extra_instructions: Optional[str] = None,
    handoffs: Optional[Sequence[Agent]] = None,
    prompt_prefix: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    name: str = "Agente Clima",
) -> Agent:
    """Especialista en Open-Meteo y en los criterios de seguridad de salto."""

    mcp_client.permitir(name, tools.WEATHER_TOOLS)
    return Agent(
        name=name,
        handoff_description="Consulta Open-Meteo y dictamina si una fecha es IDEAL, MARGINAL o NO_SEGURA para saltar.",
        instructions=_instructions(prompts.WEATHER_AGENT, extra_instructions, prompt_prefix),
        mcp_servers=[servidor_mcp],
        handoffs=list(handoffs or []),
        model=model,
    )


def make_scheduling_agent(
    servidor_mcp: MCPServer,
    extra_instructions: Optional[str] = None,
    handoffs: Optional[Sequence[Agent]] = None,
    prompt_prefix: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    name: str = "Agente Agenda",
    incluir_herramienta_clima: bool = True,
) -> Agent:
    """Especialista en agendar, listar y cancelar citas.

    `incluir_herramienta_clima` le da acceso directo a la evaluacion de clima.
    En la arquitectura descentralizada esto es necesario porque no hay un jefe
    que le pase el veredicto; en las otras dos se mantiene como red de
    seguridad (la herramienta `agendar_cita` revalida el clima de todos modos).
    """

    herramientas = list(tools.SCHEDULING_TOOLS)
    if incluir_herramienta_clima:
        herramientas.append("evaluar_condiciones_de_salto")
    mcp_client.permitir(name, herramientas)

    return Agent(
        name=name,
        handoff_description="Agenda, consulta y cancela citas de salto respetando cupos y veredicto de clima.",
        instructions=_instructions(prompts.SCHEDULING_AGENT, extra_instructions, prompt_prefix),
        mcp_servers=[servidor_mcp],
        handoffs=list(handoffs or []),
        model=model,
    )
