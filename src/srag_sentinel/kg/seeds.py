"""Versioned seeds of the closed ontology: UFs, regions, adjacency, pathogens (spec 07 §2.4).

Loading validates the invariants the graph relies on, so a bad edit fails at boot and in tests:
every UF has a region and at least one neighbour, adjacency is symmetric, and pathogen aliases
are unique across pathogens.
"""

import unicodedata
from functools import lru_cache
from importlib.resources import files
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

NATIONAL = "BR"


def fold(text: str) -> str:
    """Lower-case and strip accents: the form used to match aliases and names."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class UfSeed(BaseModel):
    """One federative unit."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str
    region: str


class PathogenSeed(BaseModel):
    """One agent of the closed pathogen ontology."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name_pt: str
    aliases: tuple[str, ...] = Field(min_length=1)


class Seeds(BaseModel):
    """Everything the static part of the graph is built from."""

    model_config = ConfigDict(frozen=True)

    regions: dict[str, str]
    ufs: tuple[UfSeed, ...]
    adjacency: dict[str, tuple[str, ...]]
    pathogens: tuple[PathogenSeed, ...]
    national_name: str

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        unknown_regions = {uf.region for uf in self.ufs} - set(self.regions)
        if unknown_regions:
            raise ValueError(f"UFs reference unknown regions: {sorted(unknown_regions)}")
        self._check_adjacency()
        self._check_aliases()
        return self

    def _check_adjacency(self) -> None:
        codes = {uf.code for uf in self.ufs}
        if set(self.adjacency) != codes:
            raise ValueError("adjacency must list exactly the seeded UFs")
        for uf, neighbours in self.adjacency.items():
            if not neighbours:
                raise ValueError(f"{uf} has no neighbour")
            for other in neighbours:
                if other == uf or other not in codes:
                    raise ValueError(f"{uf} has an invalid neighbour {other}")
                if uf not in self.adjacency[other]:
                    raise ValueError(f"adjacency is not symmetric: {uf} -> {other}")

    def _check_aliases(self) -> None:
        seen: dict[str, str] = {}
        for pathogen in self.pathogens:
            for alias in pathogen.aliases:
                key = fold(alias)
                if key in seen and seen[key] != pathogen.id:
                    raise ValueError(f"alias {alias!r} belongs to {seen[key]} and {pathogen.id}")
                seen[key] = pathogen.id

    def region_of(self, uf: str) -> str | None:
        """Region code of ``uf`` (``None`` for the national scope)."""
        return next((item.region for item in self.ufs if item.code == uf), None)

    def neighbours(self, uf: str) -> tuple[str, ...]:
        """UFs sharing a border with ``uf`` (empty for ``BR``)."""
        return self.adjacency.get(uf, ())


def _yaml(name: str) -> dict[str, Any]:
    raw = files("srag_sentinel.kg").joinpath("seed", name).read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"{name} must be a mapping")
    return loaded


@lru_cache(maxsize=1)
def load_seeds() -> Seeds:
    """Load and validate the packaged seeds."""
    ufs = _yaml("ufs.yaml")
    pathogens = _yaml("pathogens.yaml")
    return Seeds(
        regions=ufs["regions"],
        ufs=tuple(UfSeed(code=code, **fields) for code, fields in ufs["ufs"].items()),
        adjacency={uf: tuple(others) for uf, others in _yaml("adjacency.yaml").items()},
        pathogens=tuple(
            PathogenSeed(id=key, **fields) for key, fields in pathogens["pathogens"].items()
        ),
        national_name=str(ufs["national"]["name"]),
    )
