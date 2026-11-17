"""Dictionary entity linking (no LLM): UFs by name and pathogens by alias, longest match first.

UF names are matched with their accents (so the preposition "para" never becomes Pará) and
case-insensitively; pathogen aliases are matched without accents. Matching is on whole words,
so "parainfluenza" never yields "influenza" and "InfoGripe" never yields "gripe".
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from srag_sentinel.kg.seeds import NATIONAL, fold, load_seeds


@dataclass(frozen=True)
class Entities:
    """Entities found in a text, as sorted ontology ids."""

    ufs: tuple[str, ...]
    pathogens: tuple[str, ...]


def _compile(terms: list[str]) -> re.Pattern[str]:
    ordered = sorted(set(terms), key=len, reverse=True)
    body = "|".join(re.escape(term) for term in ordered)
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=1)
def _index() -> tuple[re.Pattern[str], dict[str, str], re.Pattern[str], dict[str, str]]:
    seeds = load_seeds()
    uf_by_name = {unicodedata.normalize("NFC", uf.name).casefold(): uf.code for uf in seeds.ufs}
    uf_by_name[seeds.national_name.casefold()] = NATIONAL
    pathogen_by_alias = {
        fold(alias): pathogen.id for pathogen in seeds.pathogens for alias in pathogen.aliases
    }
    return (
        _compile(list(uf_by_name)),
        uf_by_name,
        _compile(list(pathogen_by_alias)),
        pathogen_by_alias,
    )


def link_entities(text: str) -> Entities:
    """Find the UFs and pathogens mentioned in ``text``."""
    uf_pattern, uf_by_name, pathogen_pattern, pathogen_by_alias = _index()
    nfc = unicodedata.normalize("NFC", text)
    ufs = {uf_by_name[match.group(0).casefold()] for match in uf_pattern.finditer(nfc)}
    pathogens = {
        pathogen_by_alias[match.group(0)] for match in pathogen_pattern.finditer(fold(text))
    }
    return Entities(ufs=tuple(sorted(ufs)), pathogens=tuple(sorted(pathogens)))
