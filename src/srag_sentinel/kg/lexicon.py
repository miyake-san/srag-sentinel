"""Term variants for retrieval. The snowball stemmer does not unify every Portuguese inflection
(ADR 0019: ``internacao``/``internacoes``, ``vacina``/``vacinação``, ``hospital``/``hospitais``),
so each concept is searched through a small, fixed list of its forms.
"""

from collections.abc import Iterable

CONCEPTS: dict[str, tuple[str, ...]] = {
    "casos": ("casos", "caso", "notificações", "notificacoes"),
    "aumento": ("aumento", "aumentam", "alta", "sobem", "crescimento", "cresce", "elevação"),
    "queda": ("queda", "caem", "redução", "reduz", "diminui", "recuo", "recuam"),
    "internacao": ("internação", "internações", "internacoes", "internados", "internado"),
    "uti": ("uti", "leitos", "ocupação", "superlotação", "superlotados"),
    "hospital": ("hospital", "hospitais", "hospitalar", "hospitalares"),
    "obito": ("óbitos", "obitos", "mortes", "morte", "mortalidade", "morreram"),
    "vacina": ("vacina", "vacinas", "vacinação", "vacinacao", "vacinal", "cobertura", "campanha"),
    "surto": ("surto", "surtos", "alerta", "epidemia"),
    "srag": ("srag", "síndrome respiratória", "respiratória", "respiratórios", "respiratorios"),
    "gripe": ("gripe", "influenza", "h1n1", "h3n2"),
    "covid": ("covid", "covid-19", "coronavírus", "sars-cov-2"),
    "vsr": ("vsr", "bronquiolite", "sincicial"),
}
_INDEX = {form: key for key, forms in CONCEPTS.items() for form in forms}


def expand_terms(terms: Iterable[str], *, limit: int = 12) -> list[str]:
    """Return ``terms`` plus the other forms of every known concept, without duplicates.

    Order is stable (given terms first), and the result is capped so the number of
    full-text queries per question stays bounded.
    """
    seen: dict[str, None] = {}
    for term in terms:
        seen.setdefault(term.casefold(), None)
    for term in list(seen):
        concept = _INDEX.get(term)
        if concept is not None:
            for form in CONCEPTS[concept]:
                seen.setdefault(form, None)
    return list(seen)[:limit]
