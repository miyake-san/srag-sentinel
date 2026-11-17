import pytest
from pydantic import ValidationError

from srag_sentinel.kg.seeding import edge_statement
from srag_sentinel.kg.seeds import Seeds, fold, load_seeds


def test_the_packaged_seeds_load_and_cover_every_uf() -> None:
    seeds = load_seeds()

    assert len(seeds.ufs) == 27
    assert set(seeds.regions) == {"N", "NE", "CO", "SE", "S"}
    assert seeds.region_of("SP") == "SE"
    assert seeds.region_of("BR") is None


def test_every_uf_has_a_region_and_a_neighbour() -> None:
    seeds = load_seeds()

    for uf in seeds.ufs:
        assert uf.region in seeds.regions
        assert seeds.neighbours(uf.code), uf.code


def test_adjacency_is_symmetric_and_has_no_self_loops() -> None:
    seeds = load_seeds()

    for uf, neighbours in seeds.adjacency.items():
        assert uf not in neighbours
        for other in neighbours:
            assert uf in seeds.adjacency[other]


def test_known_borders_are_present() -> None:
    seeds = load_seeds()

    assert "RJ" in seeds.neighbours("SP")
    assert set(seeds.neighbours("DF")) == {"GO", "MG"}
    assert "AM" not in seeds.neighbours("SP")


def test_pathogen_aliases_do_not_collide() -> None:
    seeds = load_seeds()

    owners: dict[str, str] = {}
    for pathogen in seeds.pathogens:
        for alias in pathogen.aliases:
            assert owners.setdefault(fold(alias), pathogen.id) == pathogen.id


def test_an_asymmetric_adjacency_is_rejected() -> None:
    seeds = load_seeds()
    broken = dict(seeds.adjacency)
    broken["AC"] = ("AM",)  # AC lists AM but RO still lists AC -> RO side is missing

    with pytest.raises(ValidationError, match="symmetric"):
        Seeds(**{**seeds.model_dump(), "adjacency": broken})


def test_colliding_aliases_are_rejected() -> None:
    seeds = load_seeds()
    pathogens = [p.model_dump() for p in seeds.pathogens]
    pathogens[1]["aliases"] = [*pathogens[1]["aliases"], "Influenza A"]  # folded == influenza a

    with pytest.raises(ValidationError, match="alias"):
        Seeds(**{**seeds.model_dump(), "pathogens": pathogens})


def test_fold_removes_accents_and_case() -> None:
    assert fold("São Paulo") == "sao paulo"
    assert fold("VÍRUS") == "virus"


def test_edge_statements_only_accept_known_tables() -> None:
    assert "INSERT RELATION INTO adjacent_to" in edge_statement("adjacent_to")
    with pytest.raises(ValueError, match="unknown edge table"):
        edge_statement("adjacent_to; REMOVE TABLE uf")
