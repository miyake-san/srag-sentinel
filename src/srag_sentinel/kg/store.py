"""Knowledge-graph persistence: a port, a SurrealDB adapter and an in-memory fake for tests.

All statements are fixed templates with bound variables; ids are built by code. Edge tables come
from the closed set in ``kg.seeding``. The application connects as ``kg_writer``.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import rows, run
from srag_sentinel.kg.models import (
    ArticleNode,
    ClaimNode,
    QuarantineNode,
    ReportNode,
    SnapshotNode,
    SummaryNode,
)
from srag_sentinel.kg.seeding import edge_statement

_CITABLE = frozenset({"article", "claim", "summary"})

_SUMMARY_FIELDS = (
    "text",
    "evidence_ids",
    "produced_by",
    "judge",
    "run_id",
    "created_at",
    "valid_until",
)


class KgUnavailableError(RuntimeError):
    """The graph could not be read or written (the report degrades to flat news)."""


class KgStore(Protocol):
    """What the build step needs from the graph."""

    async def write_article(self, node: ArticleNode) -> None:
        """Upsert the article, its source and its entity edges."""
        ...

    async def write_claim(self, node: ClaimNode) -> None:
        """Upsert the claim and its ``asserts``/``concerns`` edges."""
        ...

    async def quarantine(self, node: QuarantineNode) -> None:
        """Record a rejected item outside the graph."""
        ...

    async def prune(self, now: datetime) -> int:
        """Delete expired claims and articles; return how many nodes were removed."""
        ...

    async def fresh_summary(self, region: str, now: datetime) -> SummaryNode | None:
        """The unexpired summary of ``region``, if any."""
        ...

    async def region_claims(self, region: str, now: datetime, limit: int) -> list[tuple[str, str]]:
        """Best accepted claims about the UFs of ``region`` as ``(record id, text)``."""
        ...

    async def write_summary(self, node: SummaryNode) -> None:
        """Upsert the summary and its ``summarizes`` edge to the region."""
        ...

    async def write_snapshot(self, node: SnapshotNode) -> None:
        """Upsert the metrics snapshot and link it to its UF with ``has_snapshot``."""
        ...

    async def write_report(self, node: ReportNode) -> None:
        """Upsert the report with ``describes`` (snapshot) and ``cites`` (evidence) edges."""
        ...


class SurrealKgStore:
    """:class:`KgStore` on SurrealDB."""

    def __init__(self, connection: AsyncSurrealConnection) -> None:
        self._db = connection

    async def write_article(self, node: ArticleNode) -> None:
        """Upsert the article, its source and the ``published_by``/``mentions``/``about`` edges."""
        try:
            await run(
                self._db,
                "UPSERT type::record('source', $domain) SET domain = $domain, trust = $trust",
                {"domain": node.domain, "trust": node.trust},
            )
            await run(
                self._db,
                "UPSERT type::record('article', $id) SET title = $title, snippet = $snippet, "
                "text = $text, url = $url, published_at = $published_at, sha256 = $sha256, "
                "retrieved_at = $retrieved_at, expires_at = $expires_at, run_id = $run_id",
                {
                    "id": node.id,
                    "title": node.title,
                    "snippet": node.snippet,
                    "text": node.text,
                    "url": node.url,
                    "published_at": node.published_at,
                    "sha256": node.sha256,
                    "retrieved_at": node.retrieved_at,
                    "expires_at": node.expires_at,
                    "run_id": node.run_id,
                },
            )
            await self._edge("published_by", node.id, "article", node.domain, "source", node.run_id)
            for uf in node.ufs:
                await self._edge("mentions", node.id, "article", uf, "uf", node.run_id)
            for pathogen in node.pathogens:
                await self._edge("about", node.id, "article", pathogen, "pathogen", node.run_id)
        except Exception as error:
            raise KgUnavailableError("could not write the article") from error

    async def write_claim(self, node: ClaimNode) -> None:
        """Upsert the claim, ``asserts`` from its article and ``concerns`` to its entities."""
        try:
            await run(
                self._db,
                "UPSERT type::record('claim', $id) SET type = $type, direction = $direction, "
                "text = $text, evidence_span = $span, confidence = $confidence, "
                "produced_by = $produced_by, judge = $judge, run_id = $run_id, "
                "created_at = $created_at, expires_at = $expires_at",
                {
                    "id": node.id,
                    "type": node.type,
                    "direction": node.direction,
                    "text": node.text,
                    "span": node.evidence_span,
                    "confidence": node.confidence,
                    "produced_by": node.produced_by,
                    "judge": node.judge,
                    "run_id": node.run_id,
                    "created_at": node.created_at,
                    "expires_at": node.expires_at,
                },
            )
            await self._edge(
                "asserts",
                node.article_id,
                "article",
                node.id,
                "claim",
                node.run_id,
                node.produced_by,
            )
            for uf in node.uf_codes:
                await self._edge(
                    "concerns", node.id, "claim", uf, "uf", node.run_id, node.produced_by
                )
            for pathogen in node.pathogen_ids:
                await self._edge(
                    "concerns",
                    node.id,
                    "claim",
                    pathogen,
                    "pathogen",
                    node.run_id,
                    node.produced_by,
                )
        except Exception as error:
            raise KgUnavailableError("could not write the claim") from error

    async def quarantine(self, node: QuarantineNode) -> None:
        """Append a quarantine record (random id: every rejection is kept)."""
        try:
            await run(
                self._db,
                "CREATE quarantine SET kind = $kind, reason = $reason, article_id = $article_id, "
                "run_id = $run_id, produced_by = $produced_by, created_at = $created_at",
                node.model_dump(),
            )
        except Exception as error:
            raise KgUnavailableError("could not write the quarantine record") from error

    async def prune(self, now: datetime) -> int:
        """Delete expired claims and articles (their edges go with them)."""
        try:
            removed = 0
            for table in ("claim", "article"):
                expired = await rows(  # table comes from the literal tuple above
                    self._db,
                    f"SELECT VALUE id FROM {table} WHERE expires_at < $now",  # noqa: S608
                    {"now": now},
                )
                for record in expired:
                    await run(self._db, "DELETE $record", {"record": record})
                removed += len(expired)
            return removed
        except Exception as error:
            raise KgUnavailableError("could not prune the graph") from error

    async def fresh_summary(self, region: str, now: datetime) -> SummaryNode | None:
        """The newest unexpired summary of ``region``."""
        try:
            found = await rows(
                self._db,
                "SELECT scope, text, evidence_ids, produced_by, judge, run_id, created_at, "
                "valid_until FROM summary WHERE scope = $region AND valid_until > $now "
                "ORDER BY created_at DESC LIMIT 1",
                {"region": region, "now": now},
            )
        except Exception as error:
            raise KgUnavailableError("could not read the summary") from error
        if not found:
            return None
        row = found[0]
        return SummaryNode(region=row["scope"], **{k: row[k] for k in _SUMMARY_FIELDS})

    async def region_claims(self, region: str, now: datetime, limit: int) -> list[tuple[str, str]]:
        """Highest-confidence unexpired claims about UFs of ``region``."""
        try:
            found = await rows(
                self._db,
                "SELECT record::id(id) AS rid, text FROM claim WHERE expires_at > $now AND id IN "
                "(SELECT VALUE in FROM concerns WHERE out IN "
                "(SELECT VALUE id FROM uf WHERE region = type::record('region', $region))) "
                "ORDER BY confidence DESC LIMIT $limit",
                {"region": region, "now": now, "limit": limit},
            )
        except Exception as error:
            raise KgUnavailableError("could not read region claims") from error
        return [(str(getattr(row["rid"], "id", row["rid"])), row["text"]) for row in found]

    async def write_summary(self, node: SummaryNode) -> None:
        """Upsert the summary (id = region + run) and link it to the region."""
        summary_id = f"{node.region}_{node.run_id}"
        try:
            await run(
                self._db,
                "UPSERT type::record('summary', $id) SET scope = $region, text = $text, "
                "evidence_ids = $evidence_ids, produced_by = $produced_by, judge = $judge, "
                "run_id = $run_id, created_at = $created_at, valid_until = $valid_until",
                {
                    "id": summary_id,
                    "region": node.region,
                    "text": node.text,
                    "evidence_ids": list(node.evidence_ids),
                    "produced_by": node.produced_by,
                    "judge": node.judge,
                    "run_id": node.run_id,
                    "created_at": node.created_at,
                    "valid_until": node.valid_until,
                },
            )
            await self._edge(
                "summarizes",
                summary_id,
                "summary",
                node.region,
                "region",
                node.run_id,
                node.produced_by,
            )
        except Exception as error:
            raise KgUnavailableError("could not write the summary") from error

    async def write_snapshot(self, node: SnapshotNode) -> None:
        """Upsert the snapshot and ``uf -has_snapshot-> snapshot``."""
        try:
            await run(
                self._db,
                "UPSERT type::record('snapshot', $id) SET scope = $scope, as_of = $as_of, "
                "window_days = $window_days, metrics = $metrics, run_id = $run_id, "
                "created_at = $created_at",
                {
                    "id": node.id,
                    "scope": node.scope,
                    "as_of": node.as_of,
                    "window_days": node.window_days,
                    "metrics": node.metrics,
                    "run_id": node.run_id,
                    "created_at": node.created_at,
                },
            )
            await self._edge("has_snapshot", node.scope, "uf", node.id, "snapshot", node.run_id)
        except Exception as error:
            raise KgUnavailableError("could not write the snapshot") from error

    async def write_report(self, node: ReportNode) -> None:
        """Upsert the report, ``describes`` its snapshot and ``cites`` what it used."""
        try:
            await run(
                self._db,
                "UPSERT type::record('report', $run_id) SET run_id = $run_id, "
                "generated_at = $generated_at, status = $status",
                {
                    "run_id": node.run_id,
                    "generated_at": node.generated_at,
                    "status": node.status,
                },
            )
            await self._edge(
                "describes", node.run_id, "report", node.snapshot_id, "snapshot", node.run_id
            )
            for record in node.cited:
                table, _, identifier = record.partition(":")
                if table not in _CITABLE:
                    continue
                await self._edge("cites", node.run_id, "report", identifier, table, node.run_id)
        except Exception as error:
            raise KgUnavailableError("could not write the report node") from error

    async def _edge(  # noqa: PLR0913, PLR0917 - an edge has these independent parts
        self,
        table: str,
        in_id: str,
        in_table: str,
        out_id: str,
        out_table: str,
        run_id: str,
        produced_by: str = "code",
    ) -> None:
        await run(
            self._db,
            edge_statement(table),
            {
                "id": f"{in_id}__{out_id}",
                "in_table": in_table,
                "in_id": in_id,
                "out_table": out_table,
                "out_id": out_id,
                "produced_by": produced_by,
                "run_id": run_id,
            },
        )


@dataclass
class MemoryKgStore:
    """In-memory fake with the same contract (used where no database is needed)."""

    articles: dict[str, ArticleNode] = field(default_factory=dict)
    claims: dict[str, ClaimNode] = field(default_factory=dict)
    quarantined: list[QuarantineNode] = field(default_factory=list)
    summaries: dict[str, SummaryNode] = field(default_factory=dict)
    snapshots: dict[str, SnapshotNode] = field(default_factory=dict)
    reports: dict[str, ReportNode] = field(default_factory=dict)
    fail: bool = False

    async def write_snapshot(self, node: SnapshotNode) -> None:
        """Store the snapshot."""
        self._check()
        self.snapshots[node.id] = node

    async def write_report(self, node: ReportNode) -> None:
        """Store the report node."""
        self._check()
        self.reports[node.run_id] = node

    async def fresh_summary(self, region: str, now: datetime) -> SummaryNode | None:
        """The stored summary of ``region`` if it has not expired."""
        self._check()
        node = self.summaries.get(region)
        return node if node is not None and node.valid_until > now else None

    async def region_claims(self, region: str, now: datetime, limit: int) -> list[tuple[str, str]]:
        """Claims whose UFs are in ``region`` (best confidence first)."""
        self._check()
        from srag_sentinel.kg.seeds import load_seeds  # noqa: PLC0415 - avoids a module cycle

        in_region = {uf.code for uf in load_seeds().ufs if uf.region == region}
        matching = [
            claim
            for claim in self.claims.values()
            if claim.expires_at > now and in_region & set(claim.uf_codes)
        ]
        matching.sort(key=lambda claim: -claim.confidence)
        return [(claim.id, claim.text) for claim in matching[:limit]]

    async def write_summary(self, node: SummaryNode) -> None:
        """Store the summary of its region."""
        self._check()
        self.summaries[node.region] = node

    async def write_article(self, node: ArticleNode) -> None:
        """Store the article."""
        self._check()
        self.articles[node.id] = node

    async def write_claim(self, node: ClaimNode) -> None:
        """Store the claim."""
        self._check()
        self.claims[node.id] = node

    async def quarantine(self, node: QuarantineNode) -> None:
        """Keep the rejection."""
        self._check()
        self.quarantined.append(node)

    async def prune(self, now: datetime) -> int:
        """Drop expired claims and articles."""
        self._check()
        gone_claims = [key for key, claim in self.claims.items() if claim.expires_at < now]
        gone_articles = [key for key, item in self.articles.items() if item.expires_at < now]
        for key in gone_claims:
            del self.claims[key]
        for key in gone_articles:
            del self.articles[key]
        return len(gone_claims) + len(gone_articles)

    def _check(self) -> None:
        if self.fail:
            raise KgUnavailableError("memory store set to fail")
