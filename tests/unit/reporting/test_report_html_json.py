import json
import re

from conftest import HOSTILE_TITLE, make_article, make_draft, make_narrative

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.reporting.charts import daily_chart, monthly_chart
from srag_sentinel.reporting.render import render_html, render_json, sha256_hex


def test_daily_chart_is_accessible_inline_svg_without_scripts(draft: ReportDraft) -> None:
    svg = daily_chart(draft.series)

    assert svg.startswith("<svg")
    assert 'role="img"' in svg
    assert "<title" in svg
    assert "<desc" in svg
    assert "Média móvel" in svg
    assert "<script" not in svg
    assert "<?xml" not in svg


def test_monthly_chart_marks_the_partial_month(draft: ReportDraft) -> None:
    svg = monthly_chart(draft.series)

    assert "parcial" in svg
    assert svg.count('id="monthly-title"') == 1


def test_charts_are_deterministic(draft: ReportDraft) -> None:
    assert daily_chart(draft.series) == daily_chart(draft.series)
    assert monthly_chart(draft.series) == monthly_chart(draft.series)


def test_html_shows_metrics_proxy_badge_links_and_provenance(draft: ReportDraft) -> None:
    html = render_html(draft)

    assert "-8,8%" in html  # signed, pt-BR decimal
    assert "31,2%" in html
    assert 'class="proxy"' in html
    assert "completude 53,6%" in html
    assert 'href="https://example.gov.br/a"' in html
    assert "run-123" in html
    assert "claude-sonnet-5-5" in html
    assert "plan_news@1" in html
    assert "Os casos recuaram no período." in html
    assert "9.120" in html  # thousands separator


def test_html_is_self_contained_and_has_a_strict_csp(draft: ReportDraft) -> None:
    html = render_html(draft)

    assert "<script" not in html.lower()
    assert "default-src &#39;none&#39;" in html  # attribute-escaped; browsers decode it
    assert not re.search(r'(?:src|href)="https?://', html.replace("https://example.gov.br/a", ""))
    assert "<link" not in html


def test_hostile_text_from_news_and_model_is_escaped() -> None:
    draft = make_draft(
        narrative=make_narrative(summary=HOSTILE_TITLE),
        articles=(make_article(title=HOSTILE_TITLE),),
    )

    html = render_html(draft)

    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_non_http_article_links_are_not_rendered_as_links() -> None:
    draft = make_draft(
        narrative=make_narrative(),
        articles=(make_article(url="javascript:alert(1)"),),
    )

    html = render_html(draft)

    assert "javascript:" not in html


def test_degraded_report_without_narrative_says_so_and_keeps_metrics_and_charts() -> None:
    draft = make_draft(narrative=None, degradations=("NARRATIVE_REJECTED",))

    html = render_html(draft)

    assert "Relatório degradado" in html
    assert "foi omitida" in html
    assert "Resumo" not in html
    assert "-8,8%" in html
    assert "<svg" in html


def test_json_has_versioned_schema_and_hashes_of_the_artifacts(draft: ReportDraft) -> None:
    html = render_html(draft)

    document = json.loads(render_json(draft, html=html, pdf=b"%PDF-fake"))

    assert document["schema_version"] == "1.0"
    assert document["report"]["run_id"] == "run-123"
    assert document["report"]["metrics"]["metrics"][0]["metric_id"] == "M1"
    assert len(document["report"]["series"]["daily"]) == 30
    assert document["artifacts"]["html_sha256"] == sha256_hex(html.encode("utf-8"))
    assert document["artifacts"]["pdf_sha256"] == sha256_hex(b"%PDF-fake")


def test_json_pdf_hash_is_null_when_there_is_no_pdf(draft: ReportDraft) -> None:
    document = json.loads(render_json(draft, html=render_html(draft), pdf=None))

    assert document["artifacts"]["pdf_sha256"] is None
