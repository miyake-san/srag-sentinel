"""Knowledge-graph schema, seeds, full-text search and permissions on a real SurrealDB."""

import pytest
from helpers import kg_reader_connection, kg_writer_connection

from srag_sentinel.db.client import rows, run
from srag_sentinel.db.init import init_database
from srag_sentinel.kg.seeds import load_seeds
from srag_sentinel.settings import Settings

pytestmark = pytest.mark.integration

ARTICLE = (
    "CREATE article:a1 SET title = 'Internações por síndrome respiratória aumentam em São Paulo', "
    "snippet = 'Hospitais registram mais casos de influenza.', "
    "text = 'Internações por síndrome respiratória aumentam em São Paulo. "
    "Hospitais registram mais casos de influenza.', url = 'https://example.gov.br/a', "
    "sha256 = 'x', retrieved_at = time::now(), expires_at = time::now() + 30d, run_id = 'r1'"
)


async def test_seeds_are_written_completely_and_idempotently(settings: Settings) -> None:
    await init_database(settings)  # second run must not duplicate anything

    async with kg_reader_connection(settings) as db:
        ufs = await rows(db, "SELECT VALUE code FROM uf")
        edges = await rows(db, "SELECT count() AS n FROM adjacent_to GROUP ALL")
        regions = await rows(db, "SELECT count() AS n FROM in_region GROUP ALL")
        pathogens = await rows(db, "SELECT count() AS n FROM pathogen GROUP ALL")

    seeds = load_seeds()
    assert len(ufs) == 28 and "BR" in ufs
    assert edges[0]["n"] == sum(len(v) for v in seeds.adjacency.values())
    assert regions[0]["n"] == 27
    assert pathogens[0]["n"] == len(seeds.pathogens)


async def test_traversal_follows_borders_and_regions(settings: Settings) -> None:
    async with kg_reader_connection(settings) as db:
        neighbours = await rows(db, "SELECT VALUE ->adjacent_to->uf.code FROM uf:SP")
        region = await rows(db, "SELECT VALUE ->in_region->region.name FROM uf:SP")
        same_region = await rows(db, "SELECT VALUE <-in_region<-uf.code FROM region:SE")

    assert set(neighbours[0]) == {"MG", "MS", "PR", "RJ"}
    assert region[0] == ["Sudeste"]
    assert set(same_region[0]) == {"ES", "MG", "RJ", "SP"}


async def test_a_relation_between_the_wrong_node_types_is_rejected(settings: Settings) -> None:
    async with kg_writer_connection(settings) as db:
        await run(db, ARTICLE)
        with pytest.raises(Exception, match="record<uf>"):
            await run(
                db,
                "RELATE uf:SP->adjacent_to->article:a1 "
                "SET produced_by = 'x', created_at = time::now()",
            )


async def test_pt_br_full_text_handles_accents_and_plurals(settings: Settings) -> None:
    async with kg_writer_connection(settings) as db:
        await run(db, ARTICLE)

    async with kg_reader_connection(settings) as db:
        for query in ("internações", "internacoes", "respiratorias", "respiratória", "hospitais"):
            found = await rows(db, "SELECT VALUE id FROM article WHERE text @1@ $q", {"q": query})
            assert len(found) == 1, query


async def test_claims_enforce_the_closed_enums(settings: Settings) -> None:
    async with kg_writer_connection(settings) as db:
        with pytest.raises(Exception, match="type"):
            await run(
                db,
                "CREATE claim:c1 SET type = 'made_up', direction = 'up', text = 't', "
                "evidence_span = 't', confidence = 0.9, produced_by = 'x', run_id = 'r', "
                "created_at = time::now(), expires_at = time::now() + 1d",
            )


async def test_only_the_writer_can_write_and_the_api_user_only_reads(settings: Settings) -> None:
    async with kg_reader_connection(settings) as db:
        result = await run(db, "CREATE uf:ZZ SET code = 'ZZ', name = 'Nope'")
        visible = await rows(db, "SELECT VALUE code FROM uf WHERE code = 'ZZ'")
    async with kg_writer_connection(settings) as db:
        await run(db, "CREATE uf:ZY SET code = 'ZY', name = 'Ok'")
        written = await rows(db, "SELECT VALUE code FROM uf WHERE code = 'ZY'")

    assert not (result and result[0])
    assert visible == []
    assert written == ["ZY"]
