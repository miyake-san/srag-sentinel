"""Deterministic validators for ``kg.extract_claims`` (docs/specs/07 §3.1, spec 08 §3).

Hard errors cannot be overridden by the judge: an invented span or an entity outside the
ontology never reaches the graph. Warnings are the ambiguous cases the judge may settle.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from srag_sentinel.guardrails.news import injection_rule
from srag_sentinel.kg.claims import (
    CLAIM_TYPES,
    DIRECTIONS,
    MAX_CLAIMS_PER_ARTICLE,
    ClaimDraftList,
    ExtractionInput,
)
from srag_sentinel.kg.entities import link_entities
from srag_sentinel.kg.seeds import NATIONAL, load_seeds
from srag_sentinel.llm.router.validators import Issue, Validator, max_items

_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Collapse whitespace so a span copied across a line break still matches."""
    return _SPACES.sub(" ", text).strip()


def _drafts(output: BaseModel) -> ClaimDraftList:
    assert isinstance(output, ClaimDraftList)  # noqa: S101 - registered for this task only
    return output


def _source(payload: Any) -> ExtractionInput:
    assert isinstance(payload, ExtractionInput)  # noqa: S101 - registered for this task only
    return payload


def enums(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """``type`` and ``direction`` belong to the closed enums (the schema already enforces it)."""
    return [
        Issue("bad_enum", f"claim {index}: type/direction outside the closed set")
        for index, claim in enumerate(_drafts(output).claims)
        if claim.type not in CLAIM_TYPES or claim.direction not in DIRECTIONS
    ]


def span_in_source(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Every ``evidence_span`` must occur literally in the article text."""
    text = normalise(_source(payload).text)
    return [
        Issue("invented_span", f"claim {index}: evidence_span is not in the source text")
        for index, claim in enumerate(_drafts(output).claims)
        if normalise(claim.evidence_span) not in text
    ]


def entities_in_ontology(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """Entity ids must exist; entities the dictionary did not find in the text are warnings."""
    seeds = load_seeds()
    known_ufs = {uf.code for uf in seeds.ufs} | {NATIONAL}
    known_pathogens = {pathogen.id for pathogen in seeds.pathogens}
    found = link_entities(_source(payload).text)
    issues: list[Issue] = []
    for index, claim in enumerate(_drafts(output).claims):
        for uf in claim.uf_codes:
            if uf not in known_ufs:
                issues.append(Issue("unknown_uf", f"claim {index}: {uf!r} is not in the ontology"))
            elif uf not in found.ufs:
                issues.append(
                    Issue("uf_not_in_text", f"claim {index}: {uf} not found in text", "warning")
                )
        for pathogen in claim.pathogen_ids:
            if pathogen not in known_pathogens:
                issues.append(
                    Issue("unknown_pathogen", f"claim {index}: {pathogen!r} is not in the ontology")
                )
            elif pathogen not in found.pathogens:
                issues.append(
                    Issue(
                        "pathogen_not_in_text", f"claim {index}: {pathogen} not in text", "warning"
                    )
                )
    return issues


def no_instructions(output: BaseModel, payload: Any) -> Sequence[Issue]:
    """A claim that reads like an instruction to a model is rejected."""
    return [
        Issue("instruction_in_claim", f"claim {index}: text looks like an instruction")
        for index, claim in enumerate(_drafts(output).claims)
        if injection_rule(claim.text) or injection_rule(claim.evidence_span)
    ]


def kg_validators() -> Mapping[str, Validator]:
    """Validators for the knowledge-graph tasks (extraction; summaries are added in T10c)."""
    return {
        "enums": enums,
        "span_in_source": span_in_source,
        "entities_in_ontology": entities_in_ontology,
        "no_instructions": no_instructions,
        "max_items": max_items("claims", MAX_CLAIMS_PER_ARTICLE),
    }
