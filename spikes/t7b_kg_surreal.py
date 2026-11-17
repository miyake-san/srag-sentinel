"""Spike T7b: validate the knowledge-graph building blocks on a real SurrealDB.

Checks: pt-BR FULLTEXT/BM25 (accents, plurals), RELATE into TYPE RELATION tables,
bounded traversals, and permissions of a writer vs a read-only user.
Run: SURREAL_ROOT_PASSWORD=... uv run python spikes/t7b_kg_surreal.py
"""

import asyncio
import os

from srag_sentinel.db.client import open_connection, rows, run

URL = os.environ.get("SRAG_SURREAL_URL", "ws://127.0.0.1:8000/rpc")
ROOT = {"username": "root", "password": os.environ["SURREAL_ROOT_PASSWORD"]}

SCHEMA = """
DEFINE TABLE OVERWRITE uf SCHEMAFULL;
DEFINE FIELD OVERWRITE code ON uf TYPE string;
DEFINE FIELD OVERWRITE name ON uf TYPE string;
DEFINE TABLE OVERWRITE adjacent_to TYPE RELATION IN uf OUT uf ENFORCED SCHEMAFULL;
DEFINE TABLE OVERWRITE article SCHEMAFULL;
DEFINE FIELD OVERWRITE title ON article TYPE string;
DEFINE FIELD OVERWRITE snippet ON article TYPE string;
DEFINE FIELD OVERWRITE text ON article TYPE string;
DEFINE TABLE OVERWRITE mentions TYPE RELATION IN article OUT uf ENFORCED SCHEMAFULL;
DEFINE ANALYZER OVERWRITE pt_br TOKENIZERS class FILTERS lowercase, ascii, snowball(portuguese);
DEFINE INDEX OVERWRITE article_text ON article FIELDS text FULLTEXT ANALYZER pt_br BM25;
"""


async def main() -> None:
    async with open_connection(URL, auth=ROOT) as db:
        await run(db, "REMOVE NAMESPACE IF EXISTS spike;")
        await run(db, "DEFINE NAMESPACE IF NOT EXISTS spike; USE NS spike; DEFINE DATABASE IF NOT EXISTS kg;")
        await db.use("spike", "kg")
        await run(db, SCHEMA)
        await run(
            db,
            """
            CREATE uf:sp SET code='SP', name='São Paulo';
            CREATE uf:rj SET code='RJ', name='Rio de Janeiro';
            CREATE uf:mg SET code='MG', name='Minas Gerais';
            RELATE uf:sp->adjacent_to->uf:rj; RELATE uf:rj->adjacent_to->uf:sp;
            RELATE uf:rj->adjacent_to->uf:mg; RELATE uf:mg->adjacent_to->uf:rj;
            CREATE article:a1 SET title='Internações por síndrome respiratória aumentam em São Paulo',
              snippet='Hospitais registram mais casos de influenza.',
              text='Internações por síndrome respiratória aumentam em São Paulo. Hospitais registram mais casos de influenza.';
            CREATE article:a2 SET title='Vacinação contra gripe avança', snippet='Campanha chega ao Rio.',
              text='Vacinação contra gripe avança. Campanha chega ao Rio.';
            RELATE article:a1->mentions->uf:sp;
            """,
        )
        terms = (
            "internacao internacoes internações respiratorias respiratória gripe vacinas "
            "vacina vacinacao vacinação hospital hospitais casos caso aumentam aumento"
        )
        for query in (*terms.split(), "internações respiratória", "gripe vacinação"):
            found = await rows(
                db,
                "SELECT id, search::score(1) AS score FROM article "
                "WHERE text @1@ $q ORDER BY score DESC",
                {"q": query},
            )
            print("FTS", repr(query), "->", [(str(r["id"]), round(r["score"], 3)) for r in found])

        two_hops = await rows(db, "SELECT VALUE ->adjacent_to->uf->adjacent_to->uf.code FROM uf:sp")
        print("two hops from SP:", two_hops)
        back = await rows(db, "SELECT VALUE <-mentions<-article.title FROM uf:sp")
        print("articles mentioning SP:", back)

        try:
            await run(db, "RELATE uf:sp->adjacent_to->article:a1;")
            print("RELATE to wrong type: ACCEPTED (unexpected)")
        except Exception as error:  # noqa: BLE001 - the spike reports whatever the server says
            print("RELATE to wrong type: rejected ->", str(error)[:80])

        await run(db, "DEFINE USER OVERWRITE kgw ON DATABASE PASSWORD 'w-pass' ROLES EDITOR;")
        await run(db, "DEFINE USER OVERWRITE kgr ON DATABASE PASSWORD 'r-pass' ROLES VIEWER;")

    for user, password in (("kgw", "w-pass"), ("kgr", "r-pass")):
        async with open_connection(
            URL, auth={"namespace": "spike", "database": "kg", "username": user, "password": password}
        ) as db:
            await db.use("spike", "kg")
            wrote = await run(db, "CREATE uf:zz SET code='ZZ', name='Test';")
            read = await rows(db, "SELECT code FROM uf WHERE code = 'ZZ'")
            print(user, "write ->", bool(wrote and wrote[0]), "| sees ZZ:", bool(read))

    async with open_connection(URL, auth=ROOT) as db:
        await run(db, "REMOVE NAMESPACE spike;")


asyncio.run(main())
