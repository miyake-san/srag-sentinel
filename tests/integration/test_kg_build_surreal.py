"""``build_kg`` against a real SurrealDB: provenance, idempotency, quarantine and pruning."""

from datetime import timedelta

import pytest
from helpers import kg_reader_connection, kg_writer_connection

from srag_sentinel.db.client import rows
from srag_sentinel.kg.build import build_kg
from srag_sentinel.kg.claims import ClaimDraft, ClaimDraftList
from srag_sentinel.kg.store import SurrealKgStore
from srag_sentinel.settings import Settings
from support_kg import NOW, gold_drafts, load_corpus, safe_article, scripted_router

pytestmark = pytest.mark.integration


def entry(item_id: str) -> dict:  # type: ignore[type-arg]
    return next(item for item in load_corpus() if item["id"] == item_id)


async def test_claims_edges_and_provenance_are_written(settings: Settings) -> None:
    item = entry("k01")
    router, _ = scripted_router([gold_drafts(item)])

    async with kg_writer_connection(settings) as db:
        result = await build_kg(
            [safe_article(item, trust=0.9)],
            run_id="run-1",
            router=router,
            store=SurrealKgStore(db),
            now=NOW,
        )

    assert (result.articles, result.claims) == (1, 2)
    async with kg_reader_connection(settings) as db:
        claims = await rows(
            db, "SELECT type, direction, produced_by, run_id, confidence FROM claim"
        )
        mentions = await rows(db, "SELECT VALUE out.code FROM mentions")
        about = await rows(db, "SELECT VALUE record::id(out) FROM about")
        concerns = await rows(db, "SELECT count() AS n FROM concerns GROUP ALL")
        asserted = await rows(db, "SELECT VALUE ->asserts->claim.type FROM article")
        published = await rows(db, "SELECT VALUE ->published_by->source.domain FROM article")

    assert {c["type"] for c in claims} == {"case_trend", "hospital_pressure"}
    assert all(c["produced_by"].startswith("small/fake:small/kg.extract_claims@") for c in claims)
    assert all(c["run_id"] == "run-1" for c in claims)
    assert mentions == ["SP"]
    assert set(about) == {"influenza_a", "srag_nao_especificada"}
    assert concerns[0]["n"] == 4  # two claims, each with one UF and one pathogen
    assert sorted(asserted[0]) == ["case_trend", "hospital_pressure"]
    assert published[0] == ["saude.gov.br"]


async def test_rebuilding_does_not_duplicate_nodes_or_edges(settings: Settings) -> None:
    item = entry("k03")
    router, _ = scripted_router([gold_drafts(item), gold_drafts(item)])

    async with kg_writer_connection(settings) as db:
        for _ in range(2):
            await build_kg(
                [safe_article(item)], run_id="r", router=router, store=SurrealKgStore(db), now=NOW
            )

    async with kg_reader_connection(settings) as db:
        counts = {
            table: (await rows(db, f"SELECT count() AS n FROM {table} GROUP ALL"))[0]["n"]  # noqa: S608
            for table in ("article", "claim", "asserts", "concerns", "mentions", "about")
        }

    assert counts == {
        "article": 1,
        "claim": 1,
        "asserts": 1,
        "concerns": 2,
        "mentions": 1,
        "about": 1,
    }


async def test_rejected_claims_are_quarantined_not_graphed(settings: Settings) -> None:
    item = entry("k01")
    bad = ClaimDraftList(
        claims=(ClaimDraft(type="other", text="t", evidence_span="inventado", direction="up"),)
    )
    router, _ = scripted_router([bad], [bad])

    async with kg_writer_connection(settings) as db:
        result = await build_kg(
            [safe_article(item)], run_id="r", router=router, store=SurrealKgStore(db), now=NOW
        )

    assert result.quarantined == 1
    async with kg_reader_connection(settings) as db:
        claims = await rows(db, "SELECT count() AS n FROM claim GROUP ALL")
        quarantine = await rows(db, "SELECT reason, run_id FROM quarantine")

    assert claims in ([], [{"n": 0}])
    assert "invented_span" in quarantine[0]["reason"] and quarantine[0]["run_id"] == "r"


async def test_prune_deletes_expired_claims_with_their_edges(settings: Settings) -> None:
    item = entry("k01")
    router, _ = scripted_router([gold_drafts(item)])

    async with kg_writer_connection(settings) as db:
        store = SurrealKgStore(db)
        await build_kg([safe_article(item)], run_id="r", router=router, store=store, now=NOW)
        assert await store.prune(NOW + timedelta(days=1)) == 0
        removed = await store.prune(NOW + timedelta(days=31))

    assert removed == 3
    async with kg_reader_connection(settings) as db:
        left = {
            table: await rows(db, f"SELECT count() AS n FROM {table} GROUP ALL")  # noqa: S608
            for table in ("claim", "article", "asserts", "concerns", "mentions")
        }

    assert all(value in ([], [{"n": 0}]) for value in left.values()), left
