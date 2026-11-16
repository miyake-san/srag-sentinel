"""Versioned prompt files (front matter ``id`` and ``version``) loaded as package data."""

import hashlib
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class Prompt:
    """A prompt with the identity recorded in the audit trail."""

    id: str
    version: int
    text: str
    sha256: str

    @property
    def ref(self) -> str:
        """``id@version``, written to audit events."""
        return f"{self.id}@{self.version}"


def load_prompt(name: str) -> Prompt:
    """Load ``<name>.md`` and parse its front matter."""
    raw = files("srag_sentinel.llm.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    _, header, body = raw.split("---", 2)
    meta = dict(line.split(":", 1) for line in header.strip().splitlines())
    return Prompt(
        id=meta["id"].strip(),
        version=int(meta["version"]),
        text=body.strip(),
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
