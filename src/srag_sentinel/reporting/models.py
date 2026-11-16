"""The ``report.json`` contract. Versioned so consumers can detect incompatible changes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.agent.report import ReportDraft

SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ArtifactHashes(BaseModel):
    """SHA-256 of the sibling artifacts; the PDF is ``None`` when it could not be produced."""

    model_config = ConfigDict(frozen=True)

    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ReportDocument(BaseModel):
    """Machine-readable report: the same content as the HTML plus the artifact hashes."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    report: ReportDraft
    artifacts: ArtifactHashes
