"""GraphRAG retrieval (docs/specs/07 §3.2): BM25 + bounded graph expansion + ranking.

Every query is a fixed template with bound variables; the full-text terms come from code (the
lexicon and the guide questions), never from a model. Read-only: runs as ``api_ro``.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import rows
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.kg.evidence import EvidenceItem, EvidencePack, Provenance
from srag_sentinel.kg.lexicon import expand_terms
from srag_sentinel.kg.rank import DISTANT_HOPS, Candidate, normalise_relevance, select_top
from srag_sentinel.kg.seeds import NATIONAL, load_seeds
from srag_sentinel.kg.store import KgUnavailableError

TEXT_LIMIT = 40
EXPANSION_LIMIT = 100
MAX_TERMS_PER_QUESTION = 8
# Thresholds that turn a computed metric into a question worth asking the graph.
GROWTH_THRESHOLD = 0.05
ICU_HIGH = 0.3
MORTALITY_HIGH = 0.15
VACCINATION_LOW = 0.5


@dataclass(frozen=True)
class Question:
    """A guide question derived from the metrics, with the search terms it implies."""

    text: str
    terms: tuple[str, ...]


def guide_questions(metrics: MetricsPayload) -> tuple[Question, ...]:
    """Derive the questions to ask the graph from the computed metrics (code, not a model)."""
    place = "no Brasil" if metrics.scope == NATIONAL else f"em {metrics.scope}"
    value = {metric.metric_id: metric.value for metric in metrics.metrics}
    growth = value.get("M1")
    if growth is not None and growth > GROWTH_THRESHOLD:
        trend = Question(f"Por que os casos aumentam {place}?", ("aumento", "casos", "surto"))
    elif growth is not None and growth < -GROWTH_THRESHOLD:
        trend = Question(f"Por que os casos caem {place}?", ("queda", "casos"))
    else:
        trend = Question(f"Qual a situação dos casos {place}?", ("casos", "srag"))
    questions = [trend]
    icu, mortality = value.get("M3"), value.get("M2")
    if icu is not None and icu >= ICU_HIGH:
        questions.append(
            Question(f"Há pressão hospitalar {place}?", ("uti", "internacao", "hospital"))
        )
    if mortality is not None and mortality >= MORTALITY_HIGH:
        questions.append(Question(f"Há notícias sobre óbitos {place}?", ("obito", "srag")))
    coverage = [value.get("M4_COVID"), value.get("M4_INFLUENZA")]
    if any(share is not None and share < VACCINATION_LOW for share in coverage):
        questions.append(
            Question(f"O que se sabe sobre vacinação {place}?", ("vacina", "campanha"))
        )
    return tuple(questions)


def _rid(value: Any) -> str:
    """Id part of a record id returned by the SDK (or the value itself when already plain)."""
    inner = getattr(value, "id", value)
    return str(inner)


def _flatten(values: Iterable[Any]) -> list[str]:
    flat: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            flat.extend(_flatten(value))
        elif value is not None:
            flat.append(str(value))
    return flat


@dataclass(frozen=True)
class _Ring:
    """UFs reachable from the scope: hop count and the path that reaches each."""

    hops: dict[str, int]
    paths: dict[str, str]
    national: bool = False


class GraphRetriever:
    """Read-only retrieval over the ``kg`` database."""

    def __init__(self, connection: AsyncSurrealConnection) -> None:
        self._db = connection

    async def retrieve(
        self,
        *,
        scope: str,
        questions: Sequence[Question],
        top_k: int = 12,
        max_hops: int = 2,
        now: datetime | None = None,
    ) -> EvidencePack:
        """Return up to ``top_k`` ranked, provenance-carrying evidence items."""
        moment = now or datetime.now(UTC)
        try:
            ring = await self._ring(scope, max_hops)
            found: dict[tuple[str, str], Candidate] = {}
            relevance: dict[tuple[str, str], float] = defaultdict(float)
            for question in questions:
                terms = expand_terms(question.terms, limit=MAX_TERMS_PER_QUESTION)
                for table in ("claim", "article"):
                    for term in terms:
                        for candidate, score in await self._search(table, term, ring, moment):
                            key = (candidate.kind, candidate.record_id)
                            found.setdefault(key, candidate)
                            relevance[key] += score
            for candidate in await self._expand(ring, moment):
                found.setdefault((candidate.kind, candidate.record_id), candidate)
            summaries = await self._summaries(scope, moment)
            weighted = self._with_relevance(found, relevance)
            chosen = select_top(weighted, moment, top_k - len(summaries))
            # A verified regional summary always gets a slot: it is one short, vetted item.
            chosen += select_top(summaries, moment, len(summaries))
            items = await self._to_items(chosen)
        except KgUnavailableError:
            raise
        except Exception as error:
            raise KgUnavailableError("knowledge-graph retrieval failed") from error
        return EvidencePack(scope=scope, questions=tuple(q.text for q in questions), items=items)

    # -- neighbourhood ---------------------------------------------------------------------

    async def _ring(self, scope: str, max_hops: int) -> _Ring:
        hops = {scope: 0}
        paths = {scope: f"uf:{scope}"}
        if scope == NATIONAL:
            return _Ring(hops, paths, national=True)
        seeds = load_seeds()
        region = seeds.region_of(scope)
        for neighbour in seeds.neighbours(scope):
            hops.setdefault(neighbour, 1)
            paths.setdefault(neighbour, f"uf:{scope} -adjacent_to-> uf:{neighbour}")
        if region is not None:
            for uf in seeds.ufs:
                if uf.region == region and uf.code not in hops:
                    hops[uf.code] = 1
                    paths[uf.code] = (
                        f"uf:{scope} -in_region-> region:{region} <-in_region- uf:{uf.code}"
                    )
        if max_hops >= 2:  # noqa: PLR2004 - second ring
            for middle in [code for code, hop in hops.items() if hop == 1]:
                for far in seeds.neighbours(middle):
                    if far not in hops:
                        hops[far] = 2
                        paths[far] = f"{paths[middle]} -adjacent_to-> uf:{far}"
        return _Ring(hops, paths)

    # -- candidates ------------------------------------------------------------------------

    async def _search(
        self, table: str, term: str, ring: _Ring, now: datetime
    ) -> list[tuple[Candidate, float]]:
        edge = "concerns" if table == "claim" else "mentions"
        sql = _select(table, edge, "text @1@ $term AND expires_at > $now", score=True)
        result = await rows(self._db, sql, {"term": term, "now": now, "limit": TEXT_LIMIT})
        scores = normalise_relevance([float(row["score"]) for row in result])
        return [
            (self._candidate(table, row, ring, via=f"text:{term}"), score)
            for row, score in zip(result, scores, strict=True)
        ]

    async def _expand(self, ring: _Ring, now: datetime) -> list[Candidate]:
        codes = list(ring.hops)
        candidates: list[Candidate] = []
        for table, edge in (("claim", "concerns"), ("article", "mentions")):
            sql = _select(
                table,
                edge,
                f"expires_at > $now AND id IN (SELECT VALUE in FROM {edge} WHERE out IN "  # noqa: S608
                "(SELECT VALUE id FROM uf WHERE code IN $codes))",
                score=False,
            )
            result = await rows(
                self._db, sql, {"now": now, "codes": codes, "limit": EXPANSION_LIMIT}
            )
            candidates.extend(self._candidate(table, row, ring, via=None) for row in result)
        return candidates

    async def _summaries(self, scope: str, now: datetime) -> list[Candidate]:
        """The cached, verified summary of the scope's region (if any)."""
        region = load_seeds().region_of(scope)
        if region is None:
            return []
        found = await rows(
            self._db,
            "SELECT record::id(id) AS rid, text, produced_by, judge, run_id, created_at "
            "FROM summary WHERE scope = $region AND valid_until > $now "
            "ORDER BY created_at DESC LIMIT 1",
            {"region": region, "now": now},
        )
        candidates = []
        for row in found:
            judge = row.get("judge")
            quality = float(judge["score"]) / 5 if judge else 0.8
            record_id = _rid(row["rid"])
            candidates.append(
                Candidate(
                    kind="summary",
                    record_id=record_id,
                    text=str(row["text"]),
                    graph_path=(
                        f"uf:{scope} -in_region-> region:{region} <-summarizes- summary:{record_id}"
                    ),
                    article_id=None,
                    confidence=quality,
                    trust=1.0,
                    created_at=row.get("created_at"),
                    relevance=0.0,
                    hops=1,
                    produced_by=str(row.get("produced_by") or "code"),
                    judge=judge,
                    source_domain=None,
                    run_id=row.get("run_id"),
                    url=None,
                    published_at=None,
                )
            )
        return candidates

    def _candidate(
        self, table: str, row: dict[str, Any], ring: _Ring, *, via: str | None
    ) -> Candidate:
        record_id = _rid(row["rid"])
        mentioned = _flatten([row.get("ufs") or []])
        ufs = [code for code in mentioned if code in ring.hops]
        nearest = min(ufs, key=lambda code: ring.hops[code], default=None)
        if nearest is not None:
            hops: int | None = ring.hops[nearest]
        elif mentioned:
            # About UFs outside the scope's neighbourhood. For the national scope every UF counts.
            hops = 1 if ring.national else DISTANT_HOPS
        else:
            hops = None
        edge = "concerns" if table == "claim" else "mentions"
        if nearest is not None:
            path = f"{ring.paths[nearest]} <-{edge}- {table}:{record_id}"
        else:
            path = f"{via or 'graph'} -> {table}:{record_id}"
        article_id = (
            record_id if table == "article" else _first(_record_ids(row.get("article_ids") or []))
        )
        return Candidate(
            kind=table,
            record_id=record_id,
            text=str(row["text"] if table == "claim" else row["title"]),
            graph_path=path,
            article_id=article_id,
            confidence=float(row.get("confidence") or 0.0)
            if table == "claim"
            else _number(row.get("trust")),
            trust=1.0,  # source trust is already inside the node's confidence
            created_at=row.get("created_at") or row.get("retrieved_at"),
            relevance=0.0,
            hops=hops,
            produced_by=str(row.get("produced_by") or "code"),
            judge=row.get("judge"),
            source_domain=_first(_flatten([row.get("domain") or []])),
            run_id=row.get("run_id"),
            url=row.get("url"),
            published_at=row.get("published_at"),
        )

    @staticmethod
    def _with_relevance(
        found: dict[tuple[str, str], Candidate], relevance: dict[tuple[str, str], float]
    ) -> list[Candidate]:
        top = max(relevance.values(), default=0.0)
        return [
            replace(candidate, relevance=relevance.get(key, 0.0) / top if top > 0 else 0.0)
            for key, candidate in found.items()
        ]

    async def _to_items(
        self, chosen: Sequence[tuple[Candidate, float]]
    ) -> tuple[EvidenceItem, ...]:
        article_ids = sorted({c.article_id for c, _ in chosen if c.article_id})
        articles: dict[str, dict[str, Any]] = {}
        if article_ids:
            found = await rows(
                self._db,
                "SELECT record::id(id) AS rid, url, title, published_at, run_id, "
                "->published_by->source.domain AS domain "
                "FROM article WHERE record::id(id) IN $ids",
                {"ids": article_ids},
            )
            articles = {_rid(row["rid"]): row for row in found}
        items = []
        for index, (candidate, value) in enumerate(chosen, start=1):
            article = articles.get(candidate.article_id or "", {})
            items.append(
                EvidenceItem(
                    evidence_id=f"E{index}",
                    kind=candidate.kind,
                    record_id=f"{candidate.kind}:{candidate.record_id}",
                    text=candidate.text,
                    score=round(value, 4),
                    graph_path=candidate.graph_path,
                    provenance=Provenance(
                        produced_by=candidate.produced_by,
                        judge=candidate.judge,
                        source_domain=candidate.source_domain
                        or _first(_flatten([article.get("domain") or []])),
                        run_id=candidate.run_id or article.get("run_id"),
                    ),
                    url=candidate.url or article.get("url"),
                    published_at=candidate.published_at or article.get("published_at"),
                    article_id=candidate.article_id,
                )
            )
        return tuple(items)


def _record_ids(values: Any) -> list[str]:
    """Id parts of (possibly nested) record ids returned by a traversal."""
    if isinstance(values, (list, tuple)):
        return [identifier for value in values for identifier in _record_ids(value)]
    return [] if values is None else [_rid(values)]


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _number(value: Any) -> float:
    """First number in a (possibly nested) traversal result; 0 when there is none."""
    while isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        value = value[0]
    return float(value) if value is not None else 0.0


def _select(table: str, edge: str, where: str, *, score: bool) -> str:
    """Fixed ``SELECT`` template; ``table``/``edge`` come from code, values are bound."""
    if table not in {"claim", "article"} or edge not in {"concerns", "mentions"}:
        raise ValueError("unsupported table or edge")
    if table == "claim":
        fields = (
            "record::id(id) AS rid, text, confidence, produced_by, judge, run_id, created_at, "
            f"->{edge}->uf.code AS ufs, <-asserts<-article.id AS article_ids"
        )
    else:
        fields = (
            "record::id(id) AS rid, title, url, published_at, retrieved_at, run_id, "
            f"->{edge}->uf.code AS ufs, ->published_by->source.trust AS trust, "
            "->published_by->source.domain AS domain"
        )
    scoring = ", search::score(1) AS score" if score else ""
    order = " ORDER BY score DESC" if score else ""
    # table, edge and fields are code constants (checked above); every value is bound
    return f"SELECT {fields}{scoring} FROM {table} WHERE {where}{order} LIMIT $limit"  # noqa: S608
