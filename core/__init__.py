"""Capa de dominio compartida por las tres arquitecturas de orquestacion.

La idea de este paquete es que la logica de negocio (FAQs, clima, reglas de
seguridad y agenda) sea independiente de como se orquesten los agentes.
Cambiar de arquitectura centralizada a jerarquica o descentralizada no
requiere tocar ninguno de estos modulos.
"""

__all__ = [
    "config",
    "faq",
    "weather",
    "rules",
    "scheduling",
    "tools",
    "prompts",
    "specialists",
    "cli",
    "mcp_client",
]
