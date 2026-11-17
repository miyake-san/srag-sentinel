"""G3 cases: grounded narratives pass; invented numbers, fake refs and policy breaches fail."""

from datetime import date

import pytest

from srag_sentinel.agent.schemas import Claim, Narrative
from srag_sentinel.domain.metrics import compute_metrics
from srag_sentinel.domain.models import DailyCounters
from srag_sentinel.guardrails.grounding import parse_numbers, verify_narrative

AS_OF = date(2026, 11, 12)


def counters(day: date, **kw: int) -> DailyCounters:
    base = dict.fromkeys(
        (
            "cases",
            "hosp_cases",
            "outcome_known",
            "deaths",
            "uti_known",
            "uti_yes",
            "vac_cov_known",
            "vac_cov_yes",
            "vac_flu_known",
            "vac_flu_yes",
        ),
        0,
    )
    base.update(kw)
    return DailyCounters(uf="SP", day=day, **base)


# previous 30 days: 200 cases; current 30 days: 150 cases (M1 = -25.0 %)
ROWS = [
    counters(date(2026, 9, 20), cases=200, hosp_cases=100),
    counters(
        date(2026, 11, 1),
        cases=150,
        hosp_cases=120,
        outcome_known=80,
        deaths=8,
        uti_known=100,
        uti_yes=30,
        vac_cov_known=140,
        vac_cov_yes=70,
        vac_flu_known=130,
        vac_flu_yes=52,
    ),
]
PAYLOAD = compute_metrics(
    ROWS, as_of=AS_OF, window_days=30, scope="BR", retrieved_on=date(2026, 11, 16)
)
ARTICLES = {"A1": "Fiocruz: 12 estados em alerta para SRAG, segundo o InfoGripe"}
EVIDENCE = {"E1": "InfoGripe aponta 12 estados em nível de alerta"}


def good(**changes: object) -> Narrative:
    fields: dict[str, object] = {
        "summary": "Casos de SRAG recuaram 25,0% frente à janela anterior; mortalidade em 10,0%.",
        "metric_commentary": (
            Claim(text="Queda de 25,0% nos casos (150 contra 200).", metric_refs=("M1",)),
            Claim(
                text="Mortalidade de 10,0% entre hospitalizados com desfecho (8 de 80).",
                metric_refs=("M2",),
            ),
            Claim(
                text="30,0% das internações usaram UTI (30 de 100), um proxy.", metric_refs=("M3",)
            ),
            Claim(
                text="50,0% dos casos tinham vacina contra COVID-19 (70 de 140).",
                metric_refs=("M4_COVID",),
            ),
        ),
        "news_context": (
            Claim(
                text="Segundo o InfoGripe, 12 estados estão em alerta.",
                article_refs=("A1",),
                evidence_refs=("E1",),
            ),
        ),
        "limitations": (
            "Os indicadores de UTI e vacinação são proxy e não medem ocupação nem cobertura.",
            "Dados recentes em consolidação por defasagem de notificação.",
        ),
    }
    fields.update(changes)
    return Narrative(**fields)  # type: ignore[arg-type]


def check(narrative: Narrative):
    return verify_narrative(narrative, PAYLOAD, article_texts=ARTICLES, evidence_texts=EVIDENCE)


def rules(narrative: Narrative) -> set[str]:
    return {v.rule_id for v in check(narrative).violations}


def test_a_fully_grounded_narrative_passes_with_a_single_allow_verdict() -> None:
    result = check(good())

    assert result.ok, result.feedback()
    assert [(v.rule_id, v.action) for v in result.verdicts] == [("G3.narrative", "allow")]


# ---- numbers ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("15.655 casos", [15655.0]),
        ("15 655 casos", [15655.0]),
        ("queda de 8,8%", [8.8]),
        ("1.234.567 e 1.234,5", [1234567.0, 1234.5]),
        ("M1 e M4_COVID somam 3 casos em 2026-11-12 e 12/11/2026", [3.0]),
        ("Segundo a Agência Gov (A1) e a CNN Brasil (A2), casos caem; veja E3", []),
        ("A12 e 12 casos", [12.0]),
    ],
)
def test_brazilian_number_parsing(text: str, numbers: list[float]) -> None:
    assert parse_numbers(text) == numbers


@pytest.mark.parametrize(
    "bad_summary",
    [
        "Os casos recuaram 12,4% frente à janela anterior.",  # invented percentage
        "Foram 9999 casos na janela.",  # invented count
        "A mortalidade é de 11,0%.",  # close but wrong
    ],
)
def test_invented_or_wrong_numbers_are_blocked(bad_summary: str) -> None:
    assert "G3.numeric_grounding" in rules(good(summary=bad_summary))


def test_numbers_must_match_the_metric_the_claim_cites() -> None:
    swapped = Claim(text="Mortalidade de 25,0% (M1 value used on M2).", metric_refs=("M2",))

    assert "G3.numeric_grounding" in rules(
        good(
            metric_commentary=(
                Claim(text="Queda de 25,0% nos casos.", metric_refs=("M1",)),
                swapped,
                Claim(text="30,0% usaram UTI.", metric_refs=("M3",)),
                Claim(text="50,0% vacinados.", metric_refs=("M4_COVID",)),
            )
        )
    )


def test_inline_article_references_are_not_quantities() -> None:
    # Seen with a real model: "Segundo a Agência Gov (A1) e a CNN Brasil (A2)".
    claim = Claim(
        text="Segundo a Agência Gov (A1), os casos seguem em queda.",
        article_refs=("A1",),
    )

    assert check(good(news_context=(claim,))).ok


@pytest.mark.parametrize("word", ["proxies", "proxy", "proxys", "aproximações"])
def test_the_proxy_declaration_accepts_the_plural_and_portuguese_forms(word: str) -> None:
    limitations = (
        f"M3 e M4 são {word}, não medem ocupação nem cobertura.",
        "Defasagem de notificação.",
    )

    assert check(good(limitations=limitations)).ok


def test_rounded_percentages_are_accepted() -> None:
    assert check(good(summary="Casos caíram 25% e a mortalidade foi de 10%.")).ok


def test_a_negative_sign_in_the_text_is_tolerated() -> None:
    assert check(good(summary="Variação de -25,0% nos casos.")).ok


# ---- references -------------------------------------------------------------------------


def test_unknown_metric_article_and_evidence_references_are_blocked() -> None:
    narrative = good(
        metric_commentary=(
            Claim(text="Queda de 25,0%.", metric_refs=("M1", "M9")),
            Claim(text="10,0% de mortalidade.", metric_refs=("M2",)),
            Claim(text="30,0% em UTI.", metric_refs=("M3",)),
            Claim(text="50,0% vacinados.", metric_refs=("M4_COVID",)),
        ),
        news_context=(
            Claim(
                text="Segundo uma fonte, houve alerta.", article_refs=("A7",), evidence_refs=("E9",)
            ),
        ),
    )

    assert {"G3.unknown_metric", "G3.unknown_article", "G3.unknown_evidence"} <= rules(narrative)


def test_news_statements_without_any_reference_are_blocked() -> None:
    assert "G3.uncited_news" in rules(
        good(news_context=(Claim(text="Há alerta em vários estados."),))
    )


def test_numbers_in_news_must_appear_in_the_cited_source_and_be_attributed() -> None:
    wrong = Claim(text="Segundo o InfoGripe, 15 estados estão em alerta.", article_refs=("A1",))
    unattributed = Claim(text="12 estados estão em alerta.", article_refs=("A1",))

    assert "G3.numeric_grounding" in rules(good(news_context=(wrong,)))
    assert "G3.unattributed_number" in rules(good(news_context=(unattributed,)))
    assert check(good()).ok  # the grounded and attributed version passes


@pytest.mark.parametrize(
    "text",
    [
        "Veja mais em https://exemplo.com/noticia",
        "Fonte: www.g1.globo.com",
        "Segundo g1.globo.com, há alerta.",
    ],
)
def test_links_and_domains_in_the_narrative_are_blocked(text: str) -> None:
    assert "G3.unknown_url" in rules(good(summary=f"Resumo. {text}"))


# ---- coverage and limitations -----------------------------------------------------------


@pytest.mark.parametrize("dropped", ["M1", "M2", "M3", "M4_COVID"])
def test_every_core_metric_must_be_commented(dropped: str) -> None:
    kept = tuple(c for c in good().metric_commentary if dropped not in c.metric_refs)

    result = rules(good(metric_commentary=kept))

    assert "G3.coverage" in result


def test_influenza_vaccination_also_satisfies_the_m4_requirement() -> None:
    swapped = tuple(
        c.model_copy(
            update={
                "metric_refs": ("M4_INFLUENZA",),
                "text": "40,0% vacinados contra influenza (52 de 130).",
            }
        )
        if "M4_COVID" in c.metric_refs
        else c
        for c in good().metric_commentary
    )

    assert check(good(metric_commentary=swapped)).ok


def test_proxy_metrics_and_data_maturity_must_be_declared() -> None:
    assert "G3.limitations" in rules(
        good(limitations=("Dados sujeitos a defasagem de notificação.",))
    )
    assert "G3.limitations" in rules(good(limitations=("Os indicadores são proxy.",)))
    assert "G3.limitations" in rules(good(limitations=()))


# ---- content policy ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Recomenda-se que você deve tomar antiviral.", "G3.clinical_advice"),
        ("Procure um médico e faça automedicação.", "G3.clinical_advice"),
        ("A situação é uma catástrofe e gera pânico.", "G3.alarmist"),
        ("Contato: maria@exemplo.com", "G3.pii"),
        ("CPF 529.982.247-25 aparece no texto", "G3.pii"),
    ],
)
def test_policy_violations_are_blocked(text: str, rule: str) -> None:
    assert rule in rules(good(summary=f"Resumo dos casos. {text}"))


def test_direction_must_agree_with_the_sign_of_m1() -> None:
    wrong = good(
        metric_commentary=(
            Claim(text="Aumento de 25,0% nos casos.", metric_refs=("M1",)),
            *good().metric_commentary[1:],
        )
    )

    assert "G3.direction" in rules(wrong)


def test_dates_must_be_report_dates_and_summary_must_be_short() -> None:
    assert "G3.date" in rules(good(summary="Dados de 2026-05-01 mostram queda."))
    assert check(good(summary=f"Dados até {AS_OF.isoformat()} mostram queda de 25,0%.")).ok
    assert "G3.summary_length" in rules(good(summary="palavra " * 121))


def test_every_violation_becomes_a_blocking_verdict_without_content() -> None:
    result = check(good(summary="Foram 9999 casos. Veja https://x.com"))

    assert not result.ok
    assert all(v.blocked and v.layer == "G3" for v in result.verdicts)
    dumped = " ".join(str(v.details) for v in result.verdicts)
    assert "9999" not in dumped and "https" not in dumped
    assert any("numeric_grounding" in line for line in result.feedback())
