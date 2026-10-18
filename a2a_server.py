"""Servidor A2A: expone el sistema multiagente de Parachute S.A. como un solo agente.

Envuelve la arquitectura jerarquica (`architectures/hierarchical.py`). Hacia
afuera es un unico agente A2A con tres skills; adentro, el Director delega en
sus gerentes y especialistas, que usan las herramientas del servidor MCP.

Uso (con el servidor MCP corriendo):
    python a2a_server.py        # escucha en http://127.0.0.1:9999
"""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402
from a2a.helpers import get_message_text, new_task_from_user_message, new_text_message, new_text_part  # noqa: E402
from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater  # noqa: E402
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState  # noqa: E402
from agents import OpenAIProvider, RunConfig, Runner, SQLiteSession, set_tracing_disabled  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from starlette.applications import Starlette  # noqa: E402

from architectures.hierarchical import build_agent  # noqa: E402
from core.mcp_client import crear_servidor_mcp  # noqa: E402

logger = logging.getLogger("parachute.a2a")

HOST = os.getenv("A2A_HOST", "127.0.0.1")
PORT = int(os.getenv("A2A_PORT", "9999"))

set_tracing_disabled(True)

# Todos los agentes (tambien los anidados con as_tool, que heredan el RunConfig)
# usan Groq, una API compatible con OpenAI, con el modelo de PARACHUTE_MODEL.
RUN_CONFIG = RunConfig(
    model_provider=OpenAIProvider(
        openai_client=AsyncOpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url=os.getenv("BASE_URL", "https://api.groq.com/openai/v1"),
            max_retries=8,
        ),
        use_responses=False,
    )
)


class ParachuteAgentExecutor(AgentExecutor):
    """Corre el sistema multiagente por cada mensaje recibido por A2A."""

    def __init__(self) -> None:
        # Memoria de conversacion por contexto A2A.
        self.sesiones: dict[str, SQLiteSession] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        consulta = get_message_text(context.message)
        logger.info("tarea=%s contexto=%s consulta=%r", task.id, task.context_id, consulta)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Procesando consulta...", context_id=task.context_id, task_id=task.id),
        )

        sesion = self.sesiones.setdefault(task.context_id, SQLiteSession(task.context_id))
        inicio = time.perf_counter()
        try:
            async with crear_servidor_mcp() as servidor_mcp:
                resultado = await Runner.run(
                    build_agent(servidor_mcp),
                    consulta,
                    session=sesion,
                    max_turns=15,
                    run_config=RUN_CONFIG,
                )
        except Exception as error:
            logger.exception("tarea=%s fallo", task.id)
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Error al procesar la consulta: {error}", context_id=task.context_id, task_id=task.id),
            )
            return

        respuesta = str(resultado.final_output)
        logger.info(
            "tarea=%s completada en %.1f s respuesta=%r",
            task.id,
            time.perf_counter() - inicio,
            respuesta[:200],
        )
        await updater.add_artifact(parts=[new_text_part(text=respuesta, media_type="text/plain")])
        await updater.update_status(state=TaskState.TASK_STATE_COMPLETED)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Este agente no soporta cancelar tareas.")


AGENT_CARD = AgentCard(
    name="Asistente de Parachute S.A.",
    description=(
        "Asistente de servicio al cliente de Parachute S.A. (paracaidismo en Guatemala). "
        "Responde preguntas frecuentes, revisa el clima para saltar y agenda citas."
    ),
    version="1.0.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False),
    supported_interfaces=[
        AgentInterface(protocol_binding="JSONRPC", url=f"http://{HOST}:{PORT}", protocol_version="1.0")
    ],
    skills=[
        AgentSkill(
            id="preguntas_frecuentes",
            name="Preguntas frecuentes",
            description="Responde con la base de conocimientos: precios, requisitos, horarios, pagos, salud y que llevar.",
            tags=["faq", "parachute"],
            examples=["Cuanto cuesta un salto tandem?", "Que debo llevar el dia del salto?"],
        ),
        AgentSkill(
            id="clima_para_saltar",
            name="Clima para saltar",
            description="Consulta el pronostico de Open-Meteo de una fecha y dictamina si es IDEAL, MARGINAL o NO_SEGURO.",
            tags=["clima", "open-meteo"],
            examples=["Como estara el clima el sabado para saltar?"],
        ),
        AgentSkill(
            id="agenda_de_citas",
            name="Agenda de citas",
            description="Agenda, consulta y cancela citas de salto, solo si el clima de esa fecha es seguro.",
            tags=["agenda", "citas"],
            examples=["Quiero agendar para manana a las 10:00, soy Ana Lopez, 5555-1111."],
        ),
    ],
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

    request_handler = DefaultRequestHandler(
        agent_executor=ParachuteAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=AGENT_CARD,
    )
    routes = []
    routes.extend(create_agent_card_routes(AGENT_CARD))
    routes.extend(create_jsonrpc_routes(request_handler, "/"))

    uvicorn.run(Starlette(routes=routes), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
