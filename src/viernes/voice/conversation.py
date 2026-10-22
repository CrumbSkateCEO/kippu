"""Detección local de cierre y reactivación de conversación.

No pasa por el LLM: así "gracias Viernes, eso es todo" siempre deja a Viernes
en segundo plano, aunque el modelo no interprete bien la frase.
"""

from __future__ import annotations

import re
import unicodedata

_WAKE_NAMES = ("viernes", "friday")

_CIERRE_EXACTOS = {
    "eso es todo",
    "nada mas",
    "nada mas por ahora",
    "gracias viernes",
    "gracias friday",
    "chau",
    "chau viernes",
    "adios",
    "adios viernes",
    "hasta luego",
    "nos vemos",
    "podes descansar",
    "podes quedarte en silencio",
    "quedate en silencio",
    "modo silencio",
    "eso es todo gracias",
    "gracias eso es todo",
    "gracias viernes eso es todo",
    "gracias friday eso es todo",
    "gracias viernes nada mas",
    "eso es todo viernes",
    "listo gracias viernes",
    "listo eso es todo",
}

_CIERRE_PATTERNS = [
    re.compile(r"^gracias\s+(viernes|friday)\b.{0,40}\b(eso es todo|nada mas|por ahora|est[aá]? todo)\b"),
    re.compile(r"\b(eso es todo|nada mas por ahora)\b.{0,25}\b(viernes|friday|gracias)\b"),
    re.compile(r"\b(chau|adios|hasta luego|nos vemos)\b.{0,20}\b(viernes|friday)\b"),
    re.compile(r"\b(viernes|friday)\b.{0,25}\b(eso es todo|chau|adios|descans|callad|silencio)\b"),
    re.compile(r"\b(podes|podeis|puedes)\s+(descansar|quedarte en silencio)\b"),
]


def normalizar_frase(texto: str) -> str:
    """Minúsculas, sin tildes ni puntuación, espacios colapsados."""
    descompuesto = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^\w\s]", " ", sin_tildes.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def es_cierre_conversacion(texto: str) -> bool:
    """True si el usuario está cerrando el turno y Viernes debe callarse."""
    n = normalizar_frase(texto)
    if not n:
        return False
    if n in _CIERRE_EXACTOS:
        return True
    if len(n.split()) > 16:
        return False
    return any(pat.search(n) for pat in _CIERRE_PATTERNS)


def es_despertar(texto: str) -> bool:
    """True si la frase nombra a Viernes (reactiva el modo conversación)."""
    n = normalizar_frase(texto)
    return any(re.search(rf"\b{name}\b", n) for name in _WAKE_NAMES)


def texto_despues_de_despertar(texto: str) -> str:
    """Quita el vocativo de activación y deja el pedido, si hay uno."""
    n = normalizar_frase(texto)
    n = re.sub(
        r"^(hola|oye|oime|hey|escuchame|bueno)\s+",
        "",
        n,
    )
    n = re.sub(r"^(viernes|friday)\s*,?\s*", "", n)
    n = re.sub(r"^(viernes|friday)\s+", "", n)
    return n.strip()
