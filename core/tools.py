"""Herramientas de Parachute S.A. expuestas en un solo servidor MCP.

La logica de integracion (Open-Meteo, reglas de seguridad, FAQs y agenda) se
registra aqui como herramientas del servidor MCP `mcp` (lo levanta
`mcp_server.py` con transporte Streamable HTTP). Los agentes ya no reciben
estas funciones directamente: las consumen como cliente MCP.

Convenciones:
  * Toda herramienta devuelve un dict serializable.
  * Los errores de negocio se devuelven como {"ok": False, "error": "..."} en
    lugar de lanzar excepciones, para que el agente pueda explicarselos al
    usuario en lenguaje natural.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from datetime import timedelta
from typing import Any, Dict, List

from mcp.server.mcpserver import MCPServer

from . import config, faq, scheduling, weather
from .rules import Status, evaluate_conditions

logger = logging.getLogger("parachute.mcp")

mcp = MCPServer(
    name="Parachute S.A.",
    instructions="Herramientas de FAQs, clima (Open-Meteo) y agenda de citas de Parachute S.A.",
)


def herramienta(fn):
    """Registra la funcion como herramienta del servidor MCP y loguea cada ejecucion."""

    @functools.wraps(fn)
    def envoltura(**kwargs):
        inicio = time.perf_counter()
        resultado = fn(**kwargs)
        logger.info(
            "herramienta=%s argumentos=%s ok=%s (%.0f ms)",
            fn.__name__,
            json.dumps(kwargs, ensure_ascii=False),
            resultado.get("ok"),
            (time.perf_counter() - inicio) * 1000,
        )
        return resultado

    mcp.tool()(envoltura)
    return fn


def _error(mensaje: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": mensaje, **extra}


# --- Herramientas de contexto temporal ---------------------------------------

@herramienta
def fecha_de_hoy() -> Dict[str, Any]:
    """Devuelve la fecha de hoy y la ultima fecha con pronostico disponible.

    Usala siempre antes de interpretar fechas relativas como "manana",
    "el proximo sabado" o "en dos semanas".
    """

    hoy = weather.today_local()
    limite = hoy + timedelta(days=config.MAX_FORECAST_DAYS)
    return {
        "ok": True,
        "hoy": hoy.isoformat(),
        "dia_semana": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"][hoy.weekday()],
        "ultima_fecha_con_pronostico": limite.isoformat(),
        "dias_de_pronostico": config.MAX_FORECAST_DAYS,
        "zona_horaria": config.LANDING_ZONE.timezone,
    }


# --- Herramientas de base de conocimientos (FAQs) -----------------------------

@herramienta
def buscar_en_faqs(consulta: str) -> Dict[str, Any]:
    """Busca en la base de conocimientos de FAQs de Parachute S.A.

    Args:
        consulta: Pregunta del cliente en lenguaje natural.
    """

    resultados = faq.search(consulta)
    if not resultados:
        return {
            "ok": True,
            "encontrado": False,
            "resultados": [],
            "temas_disponibles": faq.list_categories(),
            "nota": "No hay una FAQ que cubra esa consulta; no inventes la respuesta.",
        }
    return {
        "ok": True,
        "encontrado": True,
        "resultados": [r.to_dict() for r in resultados],
    }


@herramienta
def listar_temas_faq() -> Dict[str, Any]:
    """Lista las categorias y preguntas registradas en la base de conocimientos."""

    return {"ok": True, "categorias": faq.list_categories(), "preguntas": faq.list_questions()}


# --- Herramientas de clima (Open-Meteo) ---------------------------------------

@herramienta
def consultar_clima(fecha: str) -> Dict[str, Any]:
    """Consulta Open-Meteo para la zona de aterrizaje y devuelve las variables crudas.

    Devuelve rafaga de viento (wind_gusts_10m), temperatura (temperature_2m),
    precipitacion (precipitation), cobertura de nubes (cloud_cover) y viento en
    superficie (wind_speed_10m).

    Args:
        fecha: Fecha deseada en formato YYYY-MM-DD (maximo 16 dias a futuro).
    """

    try:
        snapshot = weather.get_forecast(fecha)
    except weather.DateOutOfRangeError as exc:
        return _error(str(exc), fuera_de_rango=True)
    except (ValueError, weather.WeatherError) as exc:
        return _error(str(exc))

    return {"ok": True, "ubicacion": config.LANDING_ZONE.name, "clima": snapshot.to_dict()}


@herramienta
def evaluar_condiciones_de_salto(fecha: str) -> Dict[str, Any]:
    """Consulta el clima de una fecha y aplica los criterios de seguridad de Parachute S.A.

    Es la herramienta principal para decidir si un dia sirve para saltar:
    combina Open-Meteo con los umbrales de viento, rafagas, precipitacion y
    cobertura de nubes, y devuelve un veredicto IDEAL / MARGINAL / NO_SEGURO.

    Args:
        fecha: Fecha deseada en formato YYYY-MM-DD (maximo 16 dias a futuro).
    """

    try:
        snapshot = weather.get_forecast(fecha)
    except weather.DateOutOfRangeError as exc:
        return _error(str(exc), fuera_de_rango=True)
    except (ValueError, weather.WeatherError) as exc:
        return _error(str(exc))

    veredicto = evaluate_conditions(
        wind_speed_10m=snapshot.wind_speed_10m,
        wind_gusts_10m=snapshot.wind_gusts_10m,
        precipitation=snapshot.precipitation,
        cloud_cover=snapshot.cloud_cover,
        temperature_2m=snapshot.temperature_2m,
    )
    return {
        "ok": True,
        "fecha": snapshot.fecha,
        "ubicacion": config.LANDING_ZONE.name,
        "clima": snapshot.to_dict(),
        "veredicto": veredicto.to_dict(),
    }


# --- Herramientas de agenda ---------------------------------------------------

@herramienta
def consultar_disponibilidad(fecha: str) -> Dict[str, Any]:
    """Muestra los horarios con cupo disponible para una fecha.

    Args:
        fecha: Fecha deseada en formato YYYY-MM-DD.
    """

    try:
        return {"ok": True, **scheduling.check_availability(fecha)}
    except weather.DateOutOfRangeError as exc:
        return _error(str(exc), fuera_de_rango=True)
    except (ValueError, scheduling.SchedulingError) as exc:
        return _error(str(exc))


@herramienta
def agendar_cita(
    cliente: str,
    contacto: str,
    fecha: str,
    hora: str,
    tipo_salto: str = "tandem",
) -> Dict[str, Any]:
    """Agenda una cita de salto SOLO si el clima de esa fecha lo permite.

    La herramienta vuelve a verificar el clima antes de escribir en la agenda,
    de modo que ningun agente pueda confirmar una cita en un dia NO_SEGURO.

    Args:
        cliente: Nombre completo del cliente.
        contacto: Telefono o correo del cliente.
        fecha: Fecha de la cita en formato YYYY-MM-DD.
        hora: Horario deseado (08:00, 10:00, 13:00 o 15:00).
        tipo_salto: Tipo de salto solicitado (por defecto "tandem").
    """

    try:
        snapshot = weather.get_forecast(fecha)
    except weather.DateOutOfRangeError as exc:
        return _error(str(exc), fuera_de_rango=True)
    except (ValueError, weather.WeatherError) as exc:
        return _error(f"No se puede agendar sin verificar el clima primero. {exc}")

    veredicto = evaluate_conditions(
        wind_speed_10m=snapshot.wind_speed_10m,
        wind_gusts_10m=snapshot.wind_gusts_10m,
        precipitation=snapshot.precipitation,
        cloud_cover=snapshot.cloud_cover,
        temperature_2m=snapshot.temperature_2m,
    )

    if not veredicto.apto_para_saltar:
        return _error(
            f"No se puede agendar el {snapshot.fecha}: {veredicto.resumen}",
            veredicto=veredicto.to_dict(),
            clima=snapshot.to_dict(),
            sugerencia="Ofrece al cliente evaluar otra fecha dentro de los proximos 16 dias.",
        )

    nota = f"{veredicto.estado.value}: {veredicto.resumen}"
    try:
        cita = scheduling.create_appointment(
            cliente=cliente,
            contacto=contacto,
            fecha=fecha,
            hora=hora,
            tipo_salto=tipo_salto,
            nota_clima=nota,
        )
    except (ValueError, scheduling.SchedulingError) as exc:
        return _error(str(exc))

    return {
        "ok": True,
        "cita": cita.to_dict(),
        "veredicto": veredicto.to_dict(),
        "clima": snapshot.to_dict(),
        "advertencia": (
            "Condiciones marginales: el salto se realiza unicamente en tandem con instructor "
            "experimentado y se reconfirma el dia anterior."
            if veredicto.estado is Status.MARGINAL
            else ""
        ),
    }


@herramienta
def listar_citas(cliente: str = "", fecha: str = "") -> Dict[str, Any]:
    """Lista las citas agendadas, filtrando por cliente y/o fecha si se indican.

    Args:
        cliente: Nombre (o parte del nombre) del cliente.
        fecha: Fecha en formato YYYY-MM-DD.
    """

    citas = scheduling.list_appointments(cliente=cliente or None, fecha=fecha or None)
    return {"ok": True, "total": len(citas), "citas": citas}


@herramienta
def cancelar_cita(codigo: str) -> Dict[str, Any]:
    """Cancela una cita existente usando su codigo (por ejemplo PCH-1A2B3C).

    Args:
        codigo: Codigo de la cita a cancelar.
    """

    try:
        return {"ok": True, **scheduling.cancel_appointment(codigo)}
    except scheduling.SchedulingError as exc:
        return _error(str(exc))


# --- Catalogo de herramientas por especialidad --------------------------------
# Nombres de las herramientas del servidor MCP que puede ver cada especialista.
# Agregar un requerimiento funcional nuevo solo implica registrar la
# herramienta arriba y agregar su nombre a la lista correspondiente.

FAQ_TOOLS: List[str] = ["buscar_en_faqs", "listar_temas_faq"]
WEATHER_TOOLS: List[str] = ["fecha_de_hoy", "consultar_clima", "evaluar_condiciones_de_salto"]
SCHEDULING_TOOLS: List[str] = [
    "fecha_de_hoy",
    "consultar_disponibilidad",
    "agendar_cita",
    "listar_citas",
    "cancelar_cita",
]
