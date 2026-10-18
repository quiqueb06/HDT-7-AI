"""ARQUITECTURA 2: ORQUESTACION JERARQUICA.

    Usuario
       |
       v
  [Director de Servicio]                         <- Nivel 1 (estrategico)
       |  as_tool()
       +--> [Gerente de Informacion]             <- Nivel 2 (tactico)
       |         +--> (as_tool) Agente FAQ       <- Nivel 3 (operativo)
       |
       +--> [Gerente de Operaciones de Vuelo]    <- Nivel 2 (tactico)
                 +--> (as_tool) Agente Clima     <- Nivel 3 (operativo)
                 +--> (as_tool) Agente Agenda    <- Nivel 3 (operativo)

Tres niveles. El Director no conoce Open-Meteo ni la agenda: delega en dos
gerentes de area. El Gerente de Operaciones es quien impone la regla de
negocio "primero clima, despues cita", porque sus dos subordinados estan bajo
su mando directo.

Ventajas: cada nivel tiene un contexto acotado, la regla critica vive en el
gerente del dominio y escala bien cuando se agregan mas especialistas
(basta colgar un agente nuevo del gerente que corresponda).
Desventajas: mas saltos = mas latencia y mas tokens.

Las herramientas de los agentes vienen del servidor MCP (`mcp_server.py`) y
el sistema completo se expone como un solo agente A2A (`a2a_server.py`).
"""

from __future__ import annotations

from agents import Agent
from agents.mcp import MCPServer

from core import mcp_client, prompts
from core.config import DEFAULT_MODEL
from core.specialists import make_faq_agent, make_scheduling_agent, make_weather_agent

DESCRIPCION = (
    "Director -> Gerentes de area (Informacion y Operaciones de Vuelo) -> Especialistas.\n"
    "Cada nivel delega en el inferior con as_tool()."
)

INSTRUCCIONES_GERENTE_INFO = f"""
{prompts.POLITICA_GENERAL}

Eres el Gerente de Informacion al Cliente. Tu area cubre todo lo que ya esta
documentado en la empresa: precios, requisitos, restricciones medicas,
logistica, politicas de pago y de cancelacion.

Tienes a tu cargo la herramienta `agente_faq`. Usala siempre: no respondas de
memoria. Si la FAQ no cubre la pregunta, reporta con claridad que no esta
documentada y sugiere escalar con un asesor humano.

Devuelve a tu director una respuesta breve y ya redactada para el cliente.
""".strip()

INSTRUCCIONES_GERENTE_OPS = f"""
{prompts.POLITICA_GENERAL}

Eres el Gerente de Operaciones de Vuelo. Tu area cubre el clima y la agenda de
saltos, y eres responsable de que nunca se agende una cita insegura.

Tienes a tu cargo dos herramientas:
- `agente_clima`: consulta Open-Meteo y emite el veredicto de seguridad.
- `agente_agenda`: consulta disponibilidad, agenda, lista y cancela citas.

Protocolo obligatorio de tu area:
1. Toda solicitud que involucre una fecha empieza por `agente_clima`.
2. Si el veredicto es NO_SEGURO: NO llames a `agente_agenda`. Reporta el
   motivo con los valores concretos y propon evaluar otra fecha.
3. Si el veredicto es IDEAL o MARGINAL y el cliente quiere agendar, llama a
   `agente_agenda` pasandole el veredicto junto con nombre, contacto, fecha y
   hora. En MARGINAL agrega la advertencia de tandem con instructor experimentado.
4. Si falta un dato del cliente, reportalo a tu director en lugar de inventarlo.
5. Si la fecha excede los 16 dias de pronostico, reporta la correccion.

Devuelve a tu director un reporte breve: veredicto, datos clave del clima y
el resultado de la gestion de agenda.
""".strip()

INSTRUCCIONES_DIRECTOR = f"""
{prompts.POLITICA_GENERAL}

Eres el Director de Servicio al Cliente de Parachute S.A. y el unico que habla
con el cliente. No ejecutas tareas operativas: delegas en tus dos gerentes.

- `gerencia_informacion`: preguntas sobre la empresa (precios, requisitos,
  logistica, politicas, horarios, que llevar, seguridad, salud).
- `gerencia_operaciones`: cualquier cosa que dependa de una fecha: clima,
  factibilidad del salto, agendar, consultar o cancelar citas.

Como diriges:
1. Clasifica la consulta y delega en el o los gerentes que correspondan. Si el
   cliente pregunta precio y ademas quiere agendar, delega en ambos.
2. Pasa a cada gerencia el contexto completo que necesita (fecha, nombre,
   contacto, hora), no solo un fragmento.
3. Si una gerencia reporta que falta informacion, pidesela al cliente y vuelve
   a delegar con los datos completos.
4. Nunca contradigas ni suavices un veredicto de operaciones.
5. Redacta una sola respuesta final al cliente, sin mencionar la estructura
   interna de agentes.
""".strip()


def build_agent(servidor_mcp: MCPServer) -> Agent:
    """Arma el grafo de la arquitectura jerarquica (3 niveles)."""

    # --- Nivel 3: especialistas operativos ---
    agente_faq = make_faq_agent(servidor_mcp)
    agente_clima = make_weather_agent(servidor_mcp)
    agente_agenda = make_scheduling_agent(servidor_mcp)

    # --- Nivel 2: gerentes de area ---
    gerente_informacion = Agent(
        name="Gerente de Informacion",
        instructions=INSTRUCCIONES_GERENTE_INFO,
        model=DEFAULT_MODEL,
        tools=[
            agente_faq.as_tool(
                tool_name="agente_faq",
                tool_description="Busca la respuesta en la base de conocimientos de FAQs.",
            )
        ],
    )

    mcp_client.permitir("Gerente de Operaciones de Vuelo", ["fecha_de_hoy"])
    gerente_operaciones = Agent(
        name="Gerente de Operaciones de Vuelo",
        instructions=INSTRUCCIONES_GERENTE_OPS,
        model=DEFAULT_MODEL,
        mcp_servers=[servidor_mcp],
        tools=[
            agente_clima.as_tool(
                tool_name="agente_clima",
                tool_description=(
                    "Evalua el clima de una fecha con Open-Meteo y devuelve el veredicto "
                    "IDEAL / MARGINAL / NO_SEGURO con sus valores de respaldo."
                ),
            ),
            agente_agenda.as_tool(
                tool_name="agente_agenda",
                tool_description=(
                    "Gestiona la agenda de citas (disponibilidad, agendar, listar, cancelar). "
                    "Requiere que ya exista un veredicto de clima favorable."
                ),
            ),
        ],
    )

    # --- Nivel 1: direccion ---
    mcp_client.permitir("Director de Servicio", ["fecha_de_hoy"])
    return Agent(
        name="Director de Servicio",
        instructions=INSTRUCCIONES_DIRECTOR,
        model=DEFAULT_MODEL,
        mcp_servers=[servidor_mcp],
        tools=[
            gerente_informacion.as_tool(
                tool_name="gerencia_informacion",
                tool_description=(
                    "Area de informacion al cliente: precios, requisitos, horarios, logistica, "
                    "politicas y restricciones medicas."
                ),
            ),
            gerente_operaciones.as_tool(
                tool_name="gerencia_operaciones",
                tool_description=(
                    "Area de operaciones de vuelo: clima de una fecha, factibilidad del salto y "
                    "gestion completa de citas (agendar, consultar, cancelar)."
                ),
            ),
        ],
    )
