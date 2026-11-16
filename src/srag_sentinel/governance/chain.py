"""Hash chain: canonical hashing, sealing and verification of audit events."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from srag_sentinel.governance.model import GENESIS_HASH, AuditDraft, AuditEvent


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 characters kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """SHA-256 of ``text`` as lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(value: Any) -> str:
    """Hash of any JSON-serialisable content, used for ``inputs_hash``/``outputs_hash``."""
    return f"sha256:{sha256_hex(canonical_json(value))}"


def _body(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "hash"}


def compute_hash(event: Mapping[str, Any]) -> str:
    """Hash of an event's fields (everything except ``hash`` itself, ``prev_hash`` included)."""
    return sha256_hex(canonical_json(_body(event)))


def seal(draft: AuditDraft, *, seq: int, prev_hash: str, now: datetime | None = None) -> AuditEvent:
    """Turn a draft into a sealed event linked to ``prev_hash``."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="microseconds")
    unsealed = {
        "schema_version": "audit.v1",
        **draft.model_dump(),
        "seq": seq,
        "ts": stamp,
        "prev_hash": prev_hash,
    }
    return AuditEvent.model_validate({**unsealed, "hash": compute_hash(unsealed)})


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of :func:`verify_chain`."""

    ok: bool
    checked: int
    head_hash: str | None
    failed_seq: int | None = None
    reason: str | None = None


def verify_chain(events: Sequence[AuditEvent], *, expected_head: str | None = None) -> VerifyResult:
    """Check that ``events`` form an unbroken, untampered chain.

    Detects edited fields, removed or reordered records, sequence gaps and a wrong anchor.
    Removing the newest records is detectable only against an externally stored head, which
    callers pass as ``expected_head`` (for example from the last JSONL export).
    """
    previous_hash = GENESIS_HASH
    expected_seq = 1
    for event in events:
        if event.seq != expected_seq:
            return VerifyResult(False, expected_seq - 1, previous_hash, event.seq, "sequence gap")
        if event.prev_hash != previous_hash:
            return VerifyResult(False, expected_seq - 1, previous_hash, event.seq, "broken link")
        if compute_hash(event.model_dump()) != event.hash:
            return VerifyResult(False, expected_seq - 1, previous_hash, event.seq, "hash mismatch")
        previous_hash = event.hash
        expected_seq += 1
    if expected_head is not None and previous_hash != expected_head:
        return VerifyResult(False, len(events), previous_hash, None, "head differs from anchor")
    return VerifyResult(True, len(events), previous_hash if events else None)
