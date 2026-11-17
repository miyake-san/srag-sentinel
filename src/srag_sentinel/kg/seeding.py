"""Write the static part of the graph (idempotent). Used by ``db init`` with admin credentials."""

from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import run
from srag_sentinel.kg.seeds import NATIONAL, Seeds

# Edge tables are interpolated into statements, so they come from this closed set only.
EDGE_TABLES = frozenset(
    {
        "in_region",
        "adjacent_to",
        "published_by",
        "mentions",
        "about",
        "asserts",
        "concerns",
        "has_snapshot",
        "describes",
        "cites",
        "summarizes",
    }
)


def edge_statement(table: str) -> str:
    """Idempotent ``INSERT RELATION`` for one edge table, with bound variables only."""
    if table not in EDGE_TABLES:
        raise ValueError(f"unknown edge table: {table}")
    return (
        f"INSERT RELATION INTO {table} {{ "
        f"id: type::record('{table}', $id), "
        "in: type::record($in_table, $in_id), out: type::record($out_table, $out_id), "
        "produced_by: $produced_by, created_at: time::now(), run_id: $run_id } "
        "ON DUPLICATE KEY UPDATE produced_by = $produced_by"
    )


async def seed_graph(connection: AsyncSurrealConnection, seeds: Seeds) -> None:
    """Upsert regions, UFs, pathogens and the static edges."""
    for code, name in seeds.regions.items():
        await run(
            connection,
            "UPSERT type::record('region', $code) SET code = $code, name = $name",
            {"code": code, "name": name},
        )
    for uf in seeds.ufs:
        await run(
            connection,
            "UPSERT type::record('uf', $code) SET code = $code, name = $name, "
            "region = type::record('region', $region)",
            {"code": uf.code, "name": uf.name, "region": uf.region},
        )
    await run(
        connection,
        "UPSERT type::record('uf', $code) SET code = $code, name = $name, region = NONE",
        {"code": NATIONAL, "name": seeds.national_name},
    )
    for pathogen in seeds.pathogens:
        await run(
            connection,
            "UPSERT type::record('pathogen', $id) SET name_pt = $name, aliases = $aliases",
            {"id": pathogen.id, "name": pathogen.name_pt, "aliases": list(pathogen.aliases)},
        )

    statement = edge_statement("in_region")
    for uf in seeds.ufs:
        await run(
            connection,
            statement,
            _edge(f"{uf.code}_{uf.region}", "uf", uf.code, "region", uf.region),
        )
    statement = edge_statement("adjacent_to")
    for code, neighbours in seeds.adjacency.items():
        for other in neighbours:
            await run(connection, statement, _edge(f"{code}_{other}", "uf", code, "uf", other))


def _edge(
    edge_id: str, in_table: str, in_id: str, out_table: str, out_id: str
) -> dict[str, str | None]:
    return {
        "id": edge_id,
        "in_table": in_table,
        "in_id": in_id,
        "out_table": out_table,
        "out_id": out_id,
        "produced_by": "seed",
        "run_id": None,
    }
