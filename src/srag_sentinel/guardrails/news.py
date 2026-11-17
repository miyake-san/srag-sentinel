"""G2: treat retrieved news as untrusted data (docs/specs/04 §2).

Pipeline per article: sanitise text, detect instruction-like content, check source trust, check
topic relevance and the date window, scrub PII. Survivors are wrapped as delimited data for the
LLM; nothing here ever sees or produces instructions.
"""

import html
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import yaml
from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.guardrails.pii import scrub
from srag_sentinel.guardrails.verdict import Action, GuardrailVerdict
from srag_sentinel.news.models import Article, clip

MAX_TITLE = 300

# Matched against accent-stripped, lower-case text (Portuguese and English).
_INJECTION = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(ignore|ignorar|ignora|disregard|forget|esqueca|desconsidere|desconsiderar)\b"
        r".{0,40}\b(previous|prior|above|earlier|preceding|all|any|instruc\w*|anteriores?|acima|"
        r"tudo|todas?|everything|regras|rules|prompt)\b",
        r"\bsystem prompt\b|\bprompt do sistema\b|\bdeveloper message\b",
        r"\byou are now\b|\bvoce agora e\b|\bact as\b|\baja como\b|\bfinja ser\b|\bpretend to be\b",
        r"\bnew instructions?\b|\bnovas? instruc\w*\b|\boverride (the )?(system|instructions?)\b",
        r"\breveal (your|the) (prompt|instructions?|system)\b|\brevele (o|seu) prompt\b",
        r"\bjailbreak\b|\bdo anything now\b",
        r"<\||\|>|\[/?inst\]|</?(system|assistant|user|untrusted_news)\b",
        r"\b(system|assistant)\s*:|^\s*user\s*:",
        r"\bfunction_call\b|\btool_call\b|\btool_use\b",
        r"```",
        r"\b(responda|answer|respond|reply) (apenas|only|exclusively|somente)\b",
        # role-play and persona switches
        r"\ba partir de agora\b.{0,30}\b(voce|you)\b|\bagora voce (deve|tem que|precisa)\b",
        r"\bfinja\b|\batue como\b|\bdeveloper mode\b|\bmodo desenvolvedor\b",
        r"\bsem restricoes\b|\bwithout restrictions\b|\bunrestricted\b|\bsem filtros\b",
        # attempts to manipulate a grader or a validator
        r"\b(de|de a|give|assign)\b.{0,25}\b(nota|score|grade)\b.{0,12}\b(5|10|maxima|max)\b",
        r"\bnota (5|maxima)\b|\bscore of (5|10)\b",
        r"\b(aprove|approve)\b.{0,12}\b(sem|este|esta|isto|tudo|this|it|everything|without)\b",
        r"\boverride (the )?(validation|checks?|verification)\b|\bas passed\b",
        r"\bignore\b.{0,15}\b(verificador|validacao|verification|validator|checks?)\b",
        # requests to leak instructions or secrets
        r"\b(mostre|show|print|output|imprima|exiba)\b.{0,25}"
        r"\b(instruc\w*|instructions?|chaves?|keys?|prompt)\b",
        r"\bconteudo do prompt\b|\bapi key\b|\bchaves? de api\b|\bsecrets?\b.{0,10}\bhold\b",
        # text addressed to the model rather than to a reader
        r"\b(nota|instrucao|atencao|importante|note)\b.{0,12}\b(para|ao|to)\b.{0,12}"
        r"\b(assistente|modelo|ia|llm|assistant|model|ai)\b|\batencao ia\b",
        r"\bdesconsidere o contexto\b|\bdisregard the (above|context)\b",
    )
)
_RELEVANT = (
    "srag",
    "sindrome respiratoria",
    "respirator",
    "influenza",
    "gripe",
    "covid",
    "coronavirus",
    "vsr",
    "sincicial",
    "metapneumovirus",
    "rinovirus",
    "adenovirus",
    "parainfluenza",
    "infogripe",
)
_SPACE = re.compile(r"\s+")


class NewsPolicy(BaseModel):
    """Tunable G2 settings; ``domains`` maps a domain suffix to a trust score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_trust: float = Field(default=0.5, ge=0, le=1)
    unlisted_trust: float = Field(default=0.3, ge=0, le=1)
    domains: dict[str, float] = Field(default_factory=dict)
    lookback_days: int = Field(default=30, ge=1, le=90)

    def trust_of(self, domain: str) -> float:
        """Trust of ``domain`` from the most specific matching suffix."""
        host = domain.lower().removeprefix("www.")
        matches = [
            suffix for suffix in self.domains if host == suffix or host.endswith(f".{suffix}")
        ]
        return self.domains[max(matches, key=len)] if matches else self.unlisted_trust


def load_policy() -> NewsPolicy:
    """Load the policy shipped with the package (``domains.yaml``)."""
    text = files("srag_sentinel.guardrails").joinpath("domains.yaml").read_text(encoding="utf-8")
    return NewsPolicy.model_validate(yaml.safe_load(text))


@dataclass(frozen=True)
class SafeArticle:
    """An article that passed G2, with its prompt reference and trust."""

    ref: str
    article: Article
    trust: float


@dataclass(frozen=True)
class NewsFilterResult:
    """Accepted articles (ordered by trust then recency) and every verdict."""

    accepted: tuple[SafeArticle, ...]
    verdicts: tuple[GuardrailVerdict, ...]


def sanitize_text(text: str) -> tuple[str, int]:
    """Remove control, format (zero-width, bidi, tag) characters; return text and removed count."""
    normalised = unicodedata.normalize("NFC", text)
    kept: list[str] = []
    removed = 0
    for char in normalised:
        category = unicodedata.category(char)
        if category == "Cf" or (category == "Cc" and char not in "\t\n\r "):
            removed += 1
            continue
        kept.append(" " if category in {"Cc", "Zl", "Zp"} else char)
    return _SPACE.sub(" ", "".join(kept)).strip(), removed


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def injection_rule(text: str) -> bool:
    """Whether ``text`` looks like an instruction aimed at a model rather than news."""
    plain = _plain(text)
    return any(pattern.search(plain) for pattern in _INJECTION)


def is_relevant(text: str) -> bool:
    """Whether ``text`` mentions respiratory-disease surveillance topics."""
    plain = _plain(text)
    return any(term in plain for term in _RELEVANT)


def _verdict(rule: str, action: Action, **details: str | int) -> GuardrailVerdict:
    return GuardrailVerdict("G2", rule, action, dict(details))


def _screen(
    article: Article, policy: NewsPolicy, now: datetime
) -> tuple[Article | None, list[GuardrailVerdict]]:
    """Return the sanitised article, or None with the reason it was dropped."""
    verdicts: list[GuardrailVerdict] = []
    title, hidden_title = sanitize_text(article.title)
    snippet, hidden_snippet = sanitize_text(article.snippet)
    if hidden_title + hidden_snippet:
        verdicts.append(
            _verdict(
                "G2.hidden_unicode",
                "sanitize",
                article=article.id,
                removed=hidden_title + hidden_snippet,
            )
        )

    text = f"{title} {snippet}"
    drop = None
    if injection_rule(text):
        drop = "G2.injection"
    elif not is_relevant(text):
        drop = "G2.irrelevant"
    elif policy.trust_of(article.domain) < policy.min_trust:
        drop = "G2.untrusted_source"
    elif article.published_at is not None and article.published_at < now - timedelta(
        days=policy.lookback_days
    ):
        drop = "G2.stale"
    elif article.published_at is not None and article.published_at > now + timedelta(days=1):
        drop = "G2.future_date"
    if drop:
        return None, [*verdicts, _verdict(drop, "block", article=article.id)]

    title_clean, snippet_clean = scrub(title), scrub(snippet)
    if title_clean.redactions + snippet_clean.redactions:
        verdicts.append(
            _verdict(
                "G2.pii",
                "sanitize",
                article=article.id,
                redacted=title_clean.redactions + snippet_clean.redactions,
            )
        )
    cleaned = article.model_copy(
        update={"title": clip(title_clean.text, MAX_TITLE), "snippet": clip(snippet_clean.text)}
    )
    return cleaned, verdicts


def filter_articles(
    articles: Iterable[Article], *, policy: NewsPolicy | None = None, now: datetime | None = None
) -> NewsFilterResult:
    """Apply G2 to ``articles``; the result is safe to wrap and show to a model."""
    policy = policy or load_policy()
    now = now or datetime.now(UTC)
    verdicts: list[GuardrailVerdict] = []
    survivors: list[tuple[Article, float]] = []
    seen: set[str] = set()
    for article in articles:
        if article.id in seen:
            continue
        seen.add(article.id)
        cleaned, found = _screen(article, policy, now)
        verdicts.extend(found)
        if cleaned is not None:
            survivors.append((cleaned, policy.trust_of(cleaned.domain)))

    epoch = datetime.min.replace(tzinfo=UTC)
    survivors.sort(key=lambda item: (item[1], item[0].published_at or epoch), reverse=True)
    accepted = tuple(
        SafeArticle(f"A{index}", article, trust)
        for index, (article, trust) in enumerate(survivors, 1)
    )
    dropped = sum(1 for v in verdicts if v.blocked)
    verdicts.append(_verdict("G2.summary", "allow", accepted=len(accepted), dropped=dropped))
    return NewsFilterResult(accepted, tuple(verdicts))


def wrap_untrusted(accepted: Iterable[SafeArticle]) -> str:
    """Render articles as delimited, escaped data for the model prompt.

    Every value is HTML-escaped, so article text can never close the tag or open another one.
    """
    blocks = []
    for item in accepted:
        article = item.article
        published = article.published_at.date().isoformat() if article.published_at else "unknown"
        attrs = (
            f'id="{html.escape(item.ref)}" source="{html.escape(article.source)}" '
            f'published="{published}"'
        )
        body = f"title: {html.escape(article.title)}\nsnippet: {html.escape(article.snippet)}"
        blocks.append(f"<untrusted_news {attrs}>\n{body}\n</untrusted_news>")
    return "\n".join(blocks)


def references(accepted: Iterable[SafeArticle]) -> Mapping[str, Article]:
    """Map prompt references (``A1``...) to the accepted articles."""
    return {item.ref: item.article for item in accepted}
