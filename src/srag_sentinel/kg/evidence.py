"""Evidence returned by GraphRAG retrieval: every item is citable and carries its provenance."""

import html
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceKind = Literal["article", "claim", "summary"]


class Provenance(BaseModel):
    """Who produced the item and who vouched for it."""

    model_config = ConfigDict(frozen=True)

    produced_by: str
    judge: dict[str, object] | None = None
    source_domain: str | None = None
    run_id: str | None = None


class EvidenceItem(BaseModel):
    """One piece of evidence the narrative may cite by ``evidence_id``."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(pattern=r"^E\d+$")
    kind: EvidenceKind
    record_id: str
    text: str
    score: float
    graph_path: str
    provenance: Provenance
    url: str | None = None
    published_at: datetime | None = None
    article_id: str | None = None


def wrap_evidence(pack: EvidencePack) -> str:
    """Render the pack as delimited, escaped data for the synthesis prompt.

    Every value is HTML-escaped, so evidence text can never close the tag or open another.
    """
    blocks = []
    for item in pack.items:
        source = item.provenance.source_domain or item.kind
        published = item.published_at.date().isoformat() if item.published_at else "unknown"
        attrs = (
            f'id="{html.escape(item.evidence_id)}" kind="{item.kind}" '
            f'source="{html.escape(source)}" published="{published}"'
        )
        blocks.append(
            f"<untrusted_evidence {attrs}>\n{html.escape(item.text)}\n</untrusted_evidence>"
        )
    return "\n".join(blocks)


class EvidencePack(BaseModel):
    """Ranked evidence for one report, plus the questions that drove the search."""

    model_config = ConfigDict(frozen=True)

    scope: str
    questions: tuple[str, ...]
    items: tuple[EvidenceItem, ...]

    @property
    def ids(self) -> frozenset[str]:
        """The ids the narrative is allowed to cite."""
        return frozenset(item.evidence_id for item in self.items)
