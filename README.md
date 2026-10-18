# Hoja de trabajo #7 - Protocolos Agenticos (CC3116)

**Universidad del Valle de Guatemala**  
AI ENGINEERING CREATIVITY - Cuarto Semestre  
Quique Bran - Carnet 25302

El sistema multiagente de Parachute S.A. (arquitectura **jerarquica** de la hoja #5) ahora usa
los dos protocolos agenticos:

- **MCP:** todas las herramientas de los agentes (FAQs, clima y agenda) viven en un solo
  servidor MCP con transporte **Streamable HTTP**. Los agentes son clientes MCP.
- **A2A:** el sistema multiagente completo se expone como **un solo agente A2A** con tres
  skills. La aplicacion de terminal es un cliente A2A.

```
Terminal (cliente A2A)  --A2A/JSON-RPC-->  a2a_server.py (Agente "Asistente de Parachute S.A.")
                                              |  Director -> Gerentes -> Especialistas
                                              v
                                           mcp_server.py (herramientas, Streamable HTTP)
                                              |  FAQs / Open-Meteo / agenda
```

## Componentes

| Archivo | Que hace |
|---|---|
| `mcp_server.py` | Levanta el servidor MCP en `http://127.0.0.1:8001/mcp` (Streamable HTTP). |
| `core/tools.py` | Las 9 herramientas registradas en el servidor MCP. Cada ejecucion deja un log con el nombre, los argumentos, si devolvio `ok` y cuanto tardo. |
| `core/mcp_client.py` | Conexion de los agentes al servidor MCP (`MCPServerStreamableHttp` del SDK de OpenAI Agents) con un filtro para que cada agente vea solo las herramientas de su especialidad. |
| `architectures/hierarchical.py` | Grafo de agentes (Director, gerentes y especialistas), ahora con `mcp_servers` en lugar de herramientas locales. |
| `a2a_server.py` | Servidor A2A que envuelve el sistema multiagente: Agent Card con las skills `preguntas_frecuentes`, `clima_para_saltar` y `agenda_de_citas`, y un `AgentExecutor` que corre al Director por cada mensaje. Loguea cada consulta, su duracion y la respuesta. Mantiene la memoria de la conversacion por `context_id`. |
| `core/cli.py` | Interfaz de terminal convertida en cliente A2A: lee la Agent Card, muestra las skills y envia cada consulta con el mismo `context_id`. |

Las arquitecturas centralizada y descentralizada y los evals de la hoja #6 se quitaron de este
repositorio porque usaban las herramientas locales; siguen en los repositorios de esas hojas.

## Instalacion

```
python -m venv .venv
.venv\Scriptsctivate
pip install -r requirements.txt
```

Crear un `.env` (ver `.env.example`) con la llave gratuita de [Groq](https://console.groq.com/keys):

```
GROQ_API_KEY=...
BASE_URL=https://api.groq.com/openai/v1
PARACHUTE_MODEL=openai/gpt-oss-20b
```

## Ejecucion

En tres terminales, en este orden:

```
python mcp_server.py
```

```
python a2a_server.py
```

```
python -m core.cli
```

El servidor MCP muestra un log por cada herramienta ejecutada y el servidor A2A uno por cada
consulta recibida y respondida. Para salir del cliente se escribe `salir` o se presiona Ctrl-C.

Con `PARACHUTE_WEATHER_MODE=mock` en el `.env` el servidor MCP usa clima simulado en lugar de
Open-Meteo (util para mostrar una cita confirmada aunque el pronostico real sea de lluvia).

### Nota sobre Groq

Los agentes corren en el tier gratuito de Groq. El servidor A2A apunta el SDK de agentes a Groq
con un `RunConfig`. El tier gratuito limita los tokens por minuto y por dia, y una consulta de
agenda pasa por tres niveles de agentes, asi que puede tardar uno o dos minutos.

---

> Lo que sigue es la documentacion original de la hoja #5. Las instrucciones de ejecucion de
> esa seccion ya no aplican: ahora el sistema se corre con los servidores MCP y A2A de arriba.

# Hoja de trabajo #5 - Orquestacion de sistemas multiagentes (CC3116)

Asistente multiagente para **Parachute S.A.** implementado **tres veces**, cambiando
unicamente la arquitectura de orquestacion: **centralizada**, **jerarquica** y
**descentralizada**.

Los tres programas resuelven exactamente el mismo problema:

1. Responder preguntas frecuentes desde una base de conocimientos.
2. Consultar el clima de la zona de aterrizaje en la API gratuita de
   [Open-Meteo](https://open-meteo.com/) para la fecha que pide el cliente.
3. Calendarizar la cita **solo si** las condiciones de ese dia son seguras para saltar,
   y corregir al usuario cuando pide una fecha a mas de 16 dias (limite del pronostico).

Las respuestas a las preguntas de la hoja de trabajo estan en
[`docs/respuestas.pdf`](docs/respuestas.pdf) (fuente en [`docs/respuestas.md`](docs/respuestas.md)).

---

## Instalacion

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."     # Windows: set OPENAI_API_KEY=sk-...
```

## Ejecucion

Cada arquitectura es un programa independiente con la misma interfaz:

```bash
python -m architectures.centralized       # modo conversacion
python -m architectures.hierarchical
python -m architectures.decentralized
```

Opciones disponibles en los tres:

| Opcion | Descripcion |
|---|---|
| `--demo` | Corre un guion de preguntas que ejercita los tres requerimientos |
| `--ask "texto"` | Hace una sola pregunta y termina |
| `--mock-weather` | Usa clima simulado, sin llamar a Open-Meteo |
| `--sin-traza` | Oculta la traza de agentes y herramientas |

Ejemplo:

```bash
python -m architectures.hierarchical --ask "Quiero saltar el proximo sabado, se puede?"
```

Durante la ejecucion se imprime la traza para poder comparar arquitecturas:

```
   [agente] -> Director de Servicio
   [tool]   Director de Servicio llama a gerencia_operaciones
   [agente] -> Gerente de Operaciones de Vuelo
   [tool]   Gerente de Operaciones de Vuelo llama a agente_clima
   [agente] -> Agente Clima
   [tool]   Agente Clima llama a evaluar_condiciones_de_salto
```

### Sin API key

La logica de negocio se puede verificar sin gastar tokens:

```bash
python -m core.selftest --mock    # FAQs, ventana de 16 dias, clima, reglas y agenda
pytest -q                         # 24 pruebas unitarias
```

---

## Las tres arquitecturas

### 1. Centralizada - `architectures/centralized.py`

![Arquitectura centralizada](diagrams/arquitectura_centralizada.png)

Un solo **Coordinador** conversa con el cliente y usa a los tres especialistas como
herramientas mediante `as_tool()`. Los especialistas nunca hablan con el usuario:
devuelven su resultado al coordinador, que redacta la respuesta final.

### 2. Jerarquica - `architectures/hierarchical.py`

![Arquitectura jerarquica](diagrams/arquitectura_jerarquica.png)

Tres niveles: **Director de Servicio** -> **gerencias de area** (Informacion y
Operaciones de Vuelo) -> **especialistas**. La regla critica "primero clima, despues
cita" vive en el Gerente de Operaciones, que es duenio de los dos agentes involucrados.

### 3. Descentralizada - `architectures/decentralized.py`

![Arquitectura descentralizada](diagrams/arquitectura_descentralizada.png)

Sin jefe: **Recepcion** hace el triage y transfiere el control con `handoff()`.
Cada especialista habla directo con el cliente y puede transferir a otro par.
Como ningun agente puede garantizar una regla global, la restriccion de seguridad
se aplica en codigo dentro de `agendar_cita()`.

Los diagramas se regeneran con `python diagrams/generar_diagramas.py`.

---

## Estructura del proyecto

```
core/                      capa compartida (no sabe nada de agentes)
  config.py                coordenadas, umbrales, horarios, modelo
  weather.py               cliente Open-Meteo (current / daily, ventana de 16 dias)
  rules.py                 motor de reglas: IDEAL / MARGINAL / NO_SEGURO
  faq.py                   base de conocimientos + recuperacion
  knowledge/faqs.json      contenido de las FAQs
  scheduling.py            agenda de citas con cupos por horario
  tools.py                 las 9 function_tool que usan las 3 arquitecturas
  prompts.py               instrucciones por rol
  specialists.py           fabricas de los agentes FAQ / Clima / Agenda
  cli.py                   runner comun (REPL, demo, traza)
  selftest.py              prueba de la logica sin LLM

architectures/             lo unico que cambia entre entregables
  centralized.py           orquestacion centralizada
  hierarchical.py          orquestacion jerarquica
  decentralized.py         orquestacion descentralizada

diagrams/                  diagramas SVG/PNG/Mermaid + su generador
docs/                      respuestas.md, respuestas.pdf y el generador de PDF
tests/                     pruebas unitarias de la capa compartida
```

### Por que esta separacion

Parachute S.A. advirtio que seguira agregando requerimientos funcionales. Por eso toda
la logica de integracion vive en `core/` y se expone una sola vez como herramientas:

- Agregar un requerimiento = agregar una herramienta en `core/tools.py` y colgarla del
  especialista que corresponda. Las tres arquitecturas la heredan sin cambios.
- Cambiar de arquitectura = cambiar el cableado de agentes, sin tocar integraciones
  ni reglas de negocio.

---

## Integracion con Open-Meteo

- Coordenadas fijas de la zona de aterrizaje: **14.013722, -90.771611**.
- Para **hoy** se usa el bloque `current`; para fechas futuras, el bloque `daily`
  (maximos de viento y rafagas del dia, acumulado de lluvia y promedio de nubosidad).
- Variables obtenidas: `wind_gusts_10m`, `temperature_2m`, `precipitation`,
  `cloud_cover` y `wind_speed_10m`.
- Open-Meteo pronostica hasta **16 dias**; si el cliente pide una fecha posterior,
  el sistema lo corrige y le indica la ultima fecha con pronostico disponible.

## Criterios para autorizar un salto

| Variable | Ideal | Marginal | No seguro / prohibido |
|---|---|---|---|
| Viento en superficie (`wind_speed_10m`) | < 20 km/h | 20 - 28 km/h (solo tandem experimentado) | > 28 km/h |
| Rafagas (`wind_gusts_10m`) | <= 35 km/h | - | > 35 km/h |
| Precipitacion (`precipitation`) | 0.0 mm | - | > 0.0 mm |
| Cobertura de nubes (`cloud_cover`) | < 30% | 30 - 75% | > 75% |
| Temperatura (`temperature_2m`) | informativa | informativa | no bloquea |

El veredicto global es el **peor** de los criterios. Si Open-Meteo no devuelve alguna de
las cuatro variables criticas, el resultado es `SIN_DATO` y tampoco se autoriza el salto.

## Configuracion opcional

Ver [`.env.example`](.env.example): `PARACHUTE_MODEL`, `PARACHUTE_WEATHER_MODE`
(`live` o `mock`) y `PARACHUTE_APPOINTMENTS_FILE`.
