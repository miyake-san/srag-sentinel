"""The ``kg.extract_claims`` task: a small model proposes, validators and the judge decide."""

import html
from collections.abc import Sequence

from srag_sentinel.kg.claims import ClaimDraftList, ExtractionInput
from srag_sentinel.llm.prompts import Prompt, load_prompt
from srag_sentinel.llm.router.cascade import TaskSpec

TASK_ID = "kg.extract_claims"


def extraction_prompt() -> Prompt:
    """The versioned system prompt (its ``id@version`` goes to the audit trail)."""
    return load_prompt("kg_extract_claims")


def build_user(payload: ExtractionInput, feedback: Sequence[str]) -> str:
    """The article as escaped, delimited data, plus validator feedback on a retry."""
    body = (
        f'<untrusted_news id="{html.escape(payload.article_id)}">\n'
        f"title: {html.escape(payload.title)}\nsnippet: {html.escape(payload.snippet)}\n"
        "</untrusted_news>"
    )
    if not feedback:
        return body
    notes = "\n".join(f"- {html.escape(item)}" for item in feedback)
    return f"{body}\n\nA tentativa anterior foi reprovada pelos seguintes motivos:\n{notes}"


def extraction_task() -> TaskSpec[ExtractionInput, ClaimDraftList]:
    """Everything the router needs to run claim extraction."""
    return TaskSpec(
        task_id=TASK_ID,
        output_schema=ClaimDraftList,
        system_prompt=extraction_prompt().text,
        build_user=build_user,
        judge_source=lambda payload: payload.text,
    )
