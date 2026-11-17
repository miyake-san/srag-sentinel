"""Shared builders for the knowledge-graph tests (articles, scripted routers, gold drafts)."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from srag_sentinel.guardrails.news import SafeArticle
from srag_sentinel.kg.claims import ClaimDraft, ClaimDraftList
from srag_sentinel.kg.validators import kg_validators
from srag_sentinel.llm.fake import ScriptedModel
from srag_sentinel.llm.ports import ModelError, T
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.llm.router.judge import Verdict
from srag_sentinel.llm.router.policy import load_default_policy
from srag_sentinel.news.models import Article, article_id

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
CORPUS = Path(__file__).resolve().parent / "fixtures" / "kg" / "corpus.json"


def load_corpus() -> list[dict[str, Any]]:
    """The hand-labelled headline corpus."""
    return json.loads(CORPUS.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def safe_article(
    item: dict[str, Any], *, trust: float = 1.0, domain: str = "saude.gov.br"
) -> SafeArticle:
    """A corpus item as an article that already passed G2."""
    url = f"https://{domain}/{item['id']}"
    article = Article(
        id=article_id(url),
        title=item["title"],
        source="Fonte",
        domain=domain,
        url=url,
        published_at=NOW,
        snippet=item["snippet"],
        provider="google_news_rss",
    )
    return SafeArticle(ref=f"A-{item['id']}", article=article, trust=trust)


def gold_drafts(item: dict[str, Any]) -> ClaimDraftList:
    """The labelled claims of a corpus item as extraction output."""
    return ClaimDraftList(
        claims=tuple(
            ClaimDraft(
                type=c["type"],
                text="paráfrase",
                evidence_span=c["span"],
                uf_codes=tuple(c["ufs"]),
                pathogen_ids=tuple(c["pathogens"]),
                direction=c["direction"],
            )
            for c in item["claims"]
        )
    )


class CorpusExtractor:
    """A small-model stand-in that answers each article with its gold claims, in any order.

    ``build_kg`` extracts articles concurrently, so a positional script would hand claims to the
    wrong article; this model reads the article id from the prompt instead.
    """

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self._gold = {safe_article(item).article.id: gold_drafts(item) for item in corpus}
        self.calls = 0

    @property
    def name(self) -> str:
        """Identifier recorded in provenance."""
        return "fake:small"

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        """Return the gold claims of the article named in ``user``."""
        self.calls += 1
        match = re.search(r'<untrusted_news id="([^"]+)"', user)
        if match is None or schema is not ClaimDraftList:
            raise ModelError("CorpusExtractor only answers extraction prompts")
        return self._gold[match.group(1)]  # type: ignore[return-value]


def corpus_router(corpus: list[dict[str, Any]]) -> Router:
    """A router whose small tier extracts the gold claims of ``corpus`` (judge always passes)."""
    return Router(
        load_default_policy(),
        models={"small": CorpusExtractor(corpus)},  # type: ignore[dict-item]
        validators=kg_validators() | {"schema": lambda output, payload: ()},
        judge=FixedJudge(),
    )


class FixedJudge:
    """A judge returning a fixed verdict."""

    def __init__(self, score: int = 5, *, passed: bool = True) -> None:
        self._verdict = Verdict(score=score, passed=passed)
        self.calls = 0

    async def evaluate(self, **_: object) -> Verdict:
        """Return the configured verdict."""
        self.calls += 1
        return self._verdict


def scripted_router(
    small: list[object], large: list[object] | None = None, *, judge: FixedJudge | None = None
) -> tuple[Router, dict[str, ScriptedModel]]:
    """A router over scripted ``small`` (and optional ``large``) models with KG validators."""
    models = {"small": ScriptedModel(small, model_name="fake:small")}  # type: ignore[arg-type]
    if large is not None:
        models["large"] = ScriptedModel(large, model_name="fake:large")  # type: ignore[arg-type]
    router = Router(
        load_default_policy(),
        models=models,  # type: ignore[arg-type]
        validators=kg_validators() | {"schema": lambda output, payload: ()},
        judge=judge or FixedJudge(),
    )
    return router, models
