"""Interfaz de terminal de Parachute S.A. como cliente A2A.

Ya no arma agentes localmente: descubre al agente por su Agent Card y le envia
cada consulta por el protocolo A2A. La memoria de la conversacion se mantiene
enviando siempre el mismo `context_id`.

Uso (con los servidores MCP y A2A corriendo):
    python -m core.cli
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageRequest

BANNER = """
==============================================================
  {nombre}
==============================================================
{descripcion}

Skills:
{skills}

Escribe tu consulta (o 'salir' para terminar).
""".strip()

#: Un salto por el sistema multiagente puede tardar minutos (limites del tier gratuito de Groq).
TIMEOUT_SEGUNDOS = 600


async def main() -> int:
    url = os.getenv("A2A_URL", "http://127.0.0.1:9999")

    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as http:
        try:
            card = await A2ACardResolver(httpx_client=http, base_url=url).get_agent_card()
        except httpx.HTTPError as exc:
            print(f"No se pudo conectar al agente A2A en {url}: {exc}", file=sys.stderr)
            return 1

        skills = "\n".join(f"  - {s.name}: {s.description}" for s in card.skills)
        print(BANNER.format(nombre=card.name, descripcion=card.description, skills=skills))

        cliente = await create_client(agent=card, client_config=ClientConfig(streaming=False, httpx_client=http))
        context_id = None

        while True:
            try:
                pregunta = (await asyncio.to_thread(input, "\n> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nHasta luego, cielos despejados!")
                return 0
            if not pregunta:
                continue
            if pregunta.lower() in {"salir", "exit", "quit", "q"}:
                print("Hasta luego, cielos despejados!")
                return 0

            mensaje = new_text_message(pregunta, role=Role.ROLE_USER, context_id=context_id)
            try:
                async for respuesta in cliente.send_message(SendMessageRequest(message=mensaje)):
                    if respuesta.HasField("task"):
                        context_id = respuesta.task.context_id
                    texto = get_stream_response_text(respuesta)
                    if texto:
                        print(f"\n{texto}")
            except Exception as exc:  # pragma: no cover - errores de red/servidor
                print(f"\n[error] {exc}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
