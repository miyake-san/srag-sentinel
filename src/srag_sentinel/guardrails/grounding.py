"""G3: deterministic verification of the narrative against the metrics and retrieved sources.

The LLM never calculates: every number it writes must be traceable to a metric it cites (or to
the cited article, with attribution), every reference must exist, and the text must respect the
content policy. A narrative that fails is retried once with the violations as feedback and then
dropped (fail-closed). See docs/specs/04 §2.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from srag_sentinel.agent.schemas import Claim, Narrative
from srag_sentinel.domain.metrics import MATURITY_DAYS
from srag_sentinel.domain.models import MetricResult, MetricsPayload
from srag_sentinel.guardrails.pii import scrub
from srag_sentinel.guardrails.verdict import GuardrailVerdict

MAX_SUMMARY_WORDS = 120
EPSILON = 1e-9
CORE_METRICS = ("M1", "M2", "M3")
VACCINATION_METRICS = ("M4_COVID", "M4_INFLUENZA")

# Models write COVID-19 with a non-breaking hyphen or a minus sign; read all of them as "-".
_HYPHENS = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2212: "-"}
_SEP = re.escape("." + chr(0xA0) + " ")  # thousands separators: dot, no-break space, space
_NUMBER = re.compile(rf"\d{{1,3}}(?:[{_SEP}]\d{{3}})+(?:,\d+)?|\d+(?:[.,]\d+)?")
# Disease, pathogen and outlet names that contain digits are labels, not quantities.
_NAMES_WITH_DIGITS = re.compile(r"covid-?19|sars-?cov-?2|\bh\dn\d\b|\bg1\b|\br7\b", re.IGNORECASE)
# Prompt references (metrics M1, articles A1, evidence E1) are labels, not quantities.
_METRIC_TOKEN = re.compile(r"\bM\d(?:_[A-Z]+)?\b|\b[AE]\d{1,2}\b")
_PROXY_WORD = re.compile(r"prox(?:y|ies)|aproxim")
_URL = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|gov|org|net|br|io)\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BR_DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
_CLINICAL = re.compile(
    r"\b(tome|tomar|prescri\w+|medique\w*|recomend\w+ (o )?(uso|tomar)|dose|"
    r"voce deve|você deve|procure (um )?medico|automedic\w+)\b",
    re.IGNORECASE,
)
_ALARMIST = re.compile(
    r"\b(panico|pânico|catastrofe|catástrofe|apocalipse|colapso total)\b", re.IGNORECASE
)
_UP = re.compile(r"\b(aument\w+|cresc\w+|alta|sobe|subiu|elevaç\w+|avanç\w+)\b", re.IGNORECASE)
_DOWN = re.compile(
    r"\b(queda|reduç\w+|redu[zç]\w*|diminu\w+|caiu|cai|recuo|recua\w*)\b", re.IGNORECASE
)
_SOURCE_WORD = re.compile(r"\bsegundo\b|\bde acordo com\b", re.IGNORECASE)


@dataclass(frozen=True)
class Violation:
    """One failed check; ``message`` is safe to feed back to the model for the retry."""

    rule_id: str
    location: str
    message: str


@dataclass(frozen=True)
class Verification:
    """Outcome of G3."""

    violations: tuple[Violation, ...]
    verdicts: tuple[GuardrailVerdict, ...]

    @property
    def ok(self) -> bool:
        """Whether the narrative may be used."""
        return not self.violations

    def feedback(self) -> tuple[str, ...]:
        """Violations as short lines for the retry prompt."""
        return tuple(f"{v.rule_id} at {v.location}: {v.message}" for v in self.violations)


def parse_numbers(text: str) -> list[float]:
    """Extract numbers (Brazilian formatting: ``15.655``, ``8,8``) from ``text``."""
    plain = text.translate(_HYPHENS)
    without_labels = _NAMES_WITH_DIGITS.sub(" ", _METRIC_TOKEN.sub(" ", plain))
    without_dates = _BR_DATE.sub(" ", _ISO_DATE.sub(" ", without_labels))
    return [_to_float(token) for token in _NUMBER.findall(without_dates)]


def _to_float(token: str) -> float:
    """Convert ``15.655``, ``15 655``, ``8,8`` and ``1.234,5`` to a float."""
    if "," in token:
        integer, decimal = token.split(",", 1)
        return float(f"{re.sub(f'[{_SEP}]', '', integer)}.{decimal}")
    if re.fullmatch(rf"\d{{1,3}}(?:[{_SEP}]\d{{3}})+", token):
        return float(re.sub(f"[{_SEP}]", "", token))
    return float(token)


def _metric_numbers(metric: MetricResult) -> set[float]:
    values = {float(metric.numerator), float(metric.denominator), float(abs(metric.numerator))}
    if metric.value is not None:
        values.add(abs(metric.value) * 100)
    if metric.completeness is not None:
        values.add(metric.completeness * 100)
    return values


def _global_numbers(payload: MetricsPayload) -> set[float]:
    values = {
        float(payload.window_days),
        float(payload.window_days * 2),
        float(payload.cases_current),
        float(payload.cases_previous),
        float(MATURITY_DAYS),
        30.0,
        12.0,
    }
    for note in payload.data_maturity:
        values.update(parse_numbers(note))
    return values


def _supported(number: float, candidates: Iterable[float]) -> bool:
    """Match exactly for counts, or after rounding to 0/1 decimals for percentages."""
    for candidate in candidates:
        if abs(number - candidate) < EPSILON or abs(number - round(candidate, 1)) < EPSILON:
            return True
        if float(number).is_integer() and round(candidate) == number:
            return True
    return False


def _is_year(number: float) -> bool:
    return float(number).is_integer() and 2019 <= number <= 2035  # noqa: PLR2004


def _allowed_dates(payload: MetricsPayload) -> set[date]:
    return {
        payload.as_of,
        payload.current_window.start,
        payload.previous_window.start,
        payload.previous_window.end,
    }


def _direction_conflict(claim: Claim, metrics: Mapping[str, MetricResult]) -> str | None:
    metric = metrics.get("M1")
    if "M1" not in claim.metric_refs or metric is None or metric.value is None:
        return None
    if abs(metric.value) < 0.01:  # noqa: PLR2004 - essentially flat
        return None
    says_up, says_down = bool(_UP.search(claim.text)), bool(_DOWN.search(claim.text))
    if metric.value > 0 and says_down and not says_up:
        return "text describes a decrease but M1 is positive"
    if metric.value < 0 and says_up and not says_down:
        return "text describes an increase but M1 is negative"
    return None


class _Checker:
    """Accumulates violations while walking the narrative."""

    def __init__(
        self,
        narrative: Narrative,
        payload: MetricsPayload,
        article_texts: Mapping[str, str],
        evidence_texts: Mapping[str, str],
    ) -> None:
        self.narrative = narrative
        self.payload = payload
        self.metrics = {metric.metric_id: metric for metric in payload.metrics}
        self.article_texts = article_texts
        self.evidence_texts = evidence_texts
        self.violations: list[Violation] = []

    def add(self, rule: str, location: str, message: str) -> None:
        self.violations.append(Violation(rule, location, message))

    def check_text(self, text: str, location: str, allowed: set[float]) -> None:
        """Numbers, URLs, content policy and PII for one piece of text."""
        for number in parse_numbers(text):
            if _is_year(number) or _supported(number, allowed):
                continue
            self.add(
                "G3.numeric_grounding",
                location,
                f"number {number:g} is not supported by the cited metrics",
            )
        if _URL.search(text):
            self.add(
                "G3.unknown_url", location, "links and domains are not allowed in the narrative"
            )
        if _CLINICAL.search(text):
            self.add("G3.clinical_advice", location, "clinical or treatment advice is not allowed")
        if _ALARMIST.search(text):
            self.add("G3.alarmist", location, "alarmist language is not allowed")
        if scrub(text).redactions:
            self.add("G3.pii", location, "personal data detected")
        for found in _ISO_DATE.findall(text):
            self._check_date(found, location)

    def _check_date(self, found: str, location: str) -> None:
        try:
            parsed = date.fromisoformat(found)
        except ValueError:
            self.add("G3.date", location, "invalid date")
            return
        if parsed not in _allowed_dates(self.payload):
            self.add("G3.date", location, f"date {found} is not one of the report dates")

    def check_refs(self, claim: Claim, location: str, *, is_news: bool) -> None:
        for ref in claim.metric_refs:
            if ref not in self.metrics:
                self.add("G3.unknown_metric", location, f"metric {ref} does not exist")
        for ref in claim.article_refs:
            if ref not in self.article_texts:
                self.add("G3.unknown_article", location, f"article {ref} was not retrieved")
        for ref in claim.evidence_refs:
            if ref not in self.evidence_texts:
                self.add("G3.unknown_evidence", location, f"evidence {ref} was not retrieved")
        if is_news and not (claim.article_refs or claim.evidence_refs):
            self.add("G3.uncited_news", location, "a news statement needs at least one reference")

    def metric_allowed(self, claim: Claim) -> set[float]:
        allowed = _global_numbers(self.payload)
        for ref in claim.metric_refs:
            if ref in self.metrics:
                allowed |= _metric_numbers(self.metrics[ref])
        return allowed

    def news_allowed(self, claim: Claim) -> set[float]:
        allowed = _global_numbers(self.payload)
        for ref in claim.article_refs:
            allowed.update(parse_numbers(self.article_texts.get(ref, "")))
        for ref in claim.evidence_refs:
            allowed.update(parse_numbers(self.evidence_texts.get(ref, "")))
        return allowed

    def run(self) -> list[Violation]:
        self.check_summary()
        for index, claim in enumerate(self.narrative.metric_commentary):
            location = f"metric_commentary[{index}]"
            self.check_refs(claim, location, is_news=False)
            self.check_text(claim.text, location, self.metric_allowed(claim))
            conflict = _direction_conflict(claim, self.metrics)
            if conflict:
                self.add("G3.direction", location, conflict)
        for index, claim in enumerate(self.narrative.news_context):
            location = f"news_context[{index}]"
            self.check_refs(claim, location, is_news=True)
            self.check_news_text(claim, location)
        for index, text in enumerate(self.narrative.limitations):
            self.check_text(text, f"limitations[{index}]", _global_numbers(self.payload))
        self.check_coverage()
        return self.violations

    def check_summary(self) -> None:
        summary = self.narrative.summary
        if len(summary.split()) > MAX_SUMMARY_WORDS:
            self.add("G3.summary_length", "summary", f"summary exceeds {MAX_SUMMARY_WORDS} words")
        allowed = _global_numbers(self.payload)
        for metric in self.metrics.values():
            allowed |= _metric_numbers(metric)
        self.check_text(summary, "summary", allowed)

    def check_news_text(self, claim: Claim, location: str) -> None:
        allowed = self.news_allowed(claim)
        self.check_text(claim.text, location, allowed)
        has_numbers = any(not _is_year(n) for n in parse_numbers(claim.text))
        if has_numbers and not _SOURCE_WORD.search(claim.text):
            self.add(
                "G3.unattributed_number",
                location,
                "numbers from news must be attributed ('segundo ...')",
            )

    def check_coverage(self) -> None:
        cited = {ref for claim in self.narrative.metric_commentary for ref in claim.metric_refs}
        for metric_id in CORE_METRICS:
            if metric_id not in cited:
                self.add("G3.coverage", "metric_commentary", f"no comment on {metric_id}")
        if not cited & set(VACCINATION_METRICS):
            self.add("G3.coverage", "metric_commentary", "no comment on vaccination (M4)")
        text = " ".join(self.narrative.limitations).lower()
        if any(m.is_proxy for m in self.payload.metrics) and not _PROXY_WORD.search(text):
            self.add(
                "G3.limitations",
                "limitations",
                "write the word 'proxy' in limitations for M3 and M4 (for example 'M3 é um proxy')",
            )
        if self.payload.data_maturity and not re.search(r"defasagem|consolida|notifica", text):
            self.add(
                "G3.limitations",
                "limitations",
                "notification lag / data maturity must be mentioned",
            )


def verify_narrative(
    narrative: Narrative,
    payload: MetricsPayload,
    *,
    article_texts: Mapping[str, str] | None = None,
    evidence_texts: Mapping[str, str] | None = None,
) -> Verification:
    """Run every G3 check. ``article_texts`` maps ``A1``... to the cited article's title+snippet."""
    checker = _Checker(narrative, payload, article_texts or {}, evidence_texts or {})
    violations = tuple(checker.run())
    verdicts = tuple(
        GuardrailVerdict("G3", v.rule_id, "block", {"location": v.location}) for v in violations
    ) or (GuardrailVerdict("G3", "G3.narrative", "allow"),)
    return Verification(violations, verdicts)
