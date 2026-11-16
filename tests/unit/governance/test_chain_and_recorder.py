import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from srag_sentinel.governance.chain import (
    canonical_json,
    compute_hash,
    content_hash,
    seal,
    verify_chain,
)
from srag_sentinel.governance.model import GENESIS_HASH, AuditDraft, AuditEvent
from srag_sentinel.governance.recorder import AuditRecorder
from srag_sentinel.governance.service import export_jsonl
from srag_sentinel.governance.store import AuditWriteError, MemoryAuditStore
from srag_sentinel.guardrails.verdict import GuardrailVerdict
from srag_sentinel.llm.router.events import RouterEvent

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def draft(node: str = "n", **kw: object) -> AuditDraft:
    return AuditDraft(run_id="run-1", actor="agent", node=node, event="decision", **kw)  # type: ignore[arg-type]


async def build_chain(count: int = 4) -> list[AuditEvent]:
    store = MemoryAuditStore()
    for index in range(count):
        await store.append(draft(f"n{index}", details={"i": index}))
    return await store.read_all()


# ---- hashing and sealing ---------------------------------------------------------------


def test_canonical_json_ignores_key_order_and_keeps_unicode() -> None:
    assert canonical_json({"b": 1, "a": "ação"}) == '{"a":"ação","b":1}'
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_content_hash_is_stable_and_content_sensitive() -> None:
    assert content_hash({"x": [1, 2]}) == content_hash({"x": [1, 2]})
    assert content_hash({"x": [1, 2]}) != content_hash({"x": [2, 1]})
    assert content_hash("a").startswith("sha256:")


def test_seal_links_to_the_previous_hash_and_hashes_every_field() -> None:
    first = seal(draft(), seq=1, prev_hash=GENESIS_HASH, now=NOW)
    second = seal(draft("other"), seq=2, prev_hash=first.hash, now=NOW)

    assert first.prev_hash == GENESIS_HASH
    assert second.prev_hash == first.hash
    assert compute_hash(first.model_dump()) == first.hash
    assert first.hash != second.hash
    assert first.ts == "2026-11-16T12:00:00.000000+00:00"


def test_drafts_reject_floats_and_nested_details_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        draft(details={"score": 0.5})
    with pytest.raises(ValidationError):
        draft(details={"nested": {"a": 1}})
    with pytest.raises(ValidationError):
        AuditDraft(run_id="r", actor="agent", node="n", event="decision", prompt="text")  # type: ignore[call-arg]


# ---- verification ----------------------------------------------------------------------


async def test_an_intact_chain_verifies() -> None:
    chain = await build_chain()

    result = verify_chain(chain)

    assert (result.ok, result.checked, result.head_hash) == (True, 4, chain[-1].hash)


async def test_empty_chain_is_valid() -> None:
    assert verify_chain([]).ok


async def test_editing_any_field_is_detected() -> None:
    chain = await build_chain()
    tampered = [*chain[:2], chain[2].model_copy(update={"node": "forged"}), chain[3]]

    result = verify_chain(tampered)

    assert (result.ok, result.failed_seq, result.reason) == (False, 3, "hash mismatch")


async def test_removing_a_middle_event_is_detected() -> None:
    chain = await build_chain()

    result = verify_chain([chain[0], chain[2], chain[3]])

    assert (result.ok, result.failed_seq, result.reason) == (False, 3, "sequence gap")


async def test_reordering_events_is_detected() -> None:
    chain = await build_chain()

    assert not verify_chain([chain[1], chain[0], chain[2], chain[3]]).ok


async def test_rewriting_an_event_and_its_hash_still_breaks_the_next_link() -> None:
    chain = await build_chain()
    forged_body = {**chain[1].model_dump(), "node": "forged"}
    forged = AuditEvent.model_validate({**forged_body, "hash": compute_hash(forged_body)})

    result = verify_chain([chain[0], forged, chain[2], chain[3]])

    assert (result.ok, result.failed_seq, result.reason) == (False, 3, "broken link")


async def test_a_chain_not_starting_at_genesis_is_rejected() -> None:
    chain = await build_chain()

    result = verify_chain(chain[1:])

    assert not result.ok
    assert result.failed_seq == 2


async def test_truncating_the_tail_is_caught_by_an_external_head() -> None:
    chain = await build_chain()
    anchor = chain[-1].hash

    assert verify_chain(chain[:-1]).ok  # undetectable from the chain alone
    result = verify_chain(chain[:-1], expected_head=anchor)

    assert (result.ok, result.reason) == (False, "head differs from anchor")
    assert verify_chain(chain, expected_head=anchor).ok


# ---- recorder --------------------------------------------------------------------------


async def test_recorder_queues_then_flushes_in_order_with_hashed_content() -> None:
    store = MemoryAuditStore()
    recorder = AuditRecorder("run-9", store)

    recorder.record(
        actor="tool",
        node="get_srag_metrics",
        event="tool_call",
        inputs={"uf": "BR"},
        outputs={"cases": 10},
        details={"ms": 12},
    )
    recorder.record(actor="agent", node="synthesize", event="llm_call", details={"tier": "large"})
    assert store.events == []  # nothing is written before flush

    written = await recorder.flush()

    assert [e.node for e in written] == ["get_srag_metrics", "synthesize"]
    assert written[0].inputs_hash == content_hash({"uf": "BR"})
    assert "cases" not in written[0].model_dump_json()  # content itself is never stored
    assert verify_chain(store.events).ok
    assert await recorder.flush() == []


async def test_recorder_converts_guardrail_verdicts_and_router_events() -> None:
    store = MemoryAuditStore()
    recorder = AuditRecorder("run-9", store)

    recorder.record_verdicts([GuardrailVerdict("G1", "G1.uf", "block", {"field": "uf"})])
    sink = recorder.router_sink()
    sink.emit(
        RouterEvent("router_decision", "kg.extract_claims", "small", 1, {"reason": "first_choice"})
    )
    sink.emit(
        RouterEvent("judge_verdict", "kg.extract_claims", "small", 1, {"score": 2, "passed": False})
    )
    sink.emit(RouterEvent("validation", "kg.extract_claims", "small", 1, {"errors": 1}))
    await recorder.flush()

    events = {e.event for e in store.events}
    assert events == {"guardrail_verdict", "router_decision", "judge_verdict", "decision"}
    verdict = store.events[0]
    assert (verdict.actor, verdict.node) == ("guardrail", "G1")
    assert verdict.details["rule_id"] == "G1.uf"


async def test_a_failing_store_aborts_the_flush_and_keeps_the_rest_queued() -> None:
    class Failing(MemoryAuditStore):
        async def append(self, draft: AuditDraft) -> AuditEvent:
            raise AuditWriteError("rejected")

    recorder = AuditRecorder("run-1", Failing())
    recorder.record(actor="agent", node="n", event="decision")

    with pytest.raises(AuditWriteError):
        await recorder.flush()
    with pytest.raises(AuditWriteError):
        await recorder.flush()  # still pending: nothing was silently dropped


# ---- export ----------------------------------------------------------------------------


async def test_export_writes_one_json_line_per_event_and_returns_the_head(tmp_path: Path) -> None:
    chain = await build_chain(3)
    target = tmp_path / "audit.jsonl"

    head = export_jsonl(chain, target)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[-1])["hash"] == head == chain[-1].hash


def test_export_of_an_empty_chain_has_no_head(tmp_path: Path) -> None:
    assert export_jsonl([], tmp_path / "e.jsonl") is None
