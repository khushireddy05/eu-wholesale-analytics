"""The AI layer's guardrails.

The value of this stage depends entirely on the narrative being traceable, so
the verification step is what actually gets tested here.
"""

from __future__ import annotations

import pandas as pd

from eu_wholesale.ai.evidence import EvidenceBuilder, build_evidence, context_block
from eu_wholesale.ai.insights import (deterministic_narrative, generate_insights,
                                      verify_narrative, write_insights)


def _pack() -> EvidenceBuilder:
    ev = EvidenceBuilder()
    ev.add("Group", "Revenue, last 12 months", 2446.6, "EUR m", "mart_market")
    ev.add("Group", "Revenue growth year on year", 12.5, "%", "mart_market")
    return ev


def test_verification_accepts_figures_drawn_from_the_pack():
    text = "Revenue reached EUR 2,446.6m [F001], up 12.5% [F002]."
    report = verify_narrative(text, _pack())
    assert (report["status"] == "SUPPORTED").all()
    assert report.attrs["citations_used"] == 2


def test_verification_flags_a_number_the_model_invented():
    """A figure that is arithmetically plausible but was never supplied."""
    text = ("Revenue reached EUR 2,446.6m [F001], and the second half "
            "contributed EUR 1,308.2m.")
    report = verify_narrative(text, _pack())
    flagged = report[report["status"] == "UNSUPPORTED"]["figure"].tolist()
    assert "1,308.2" in flagged


def test_verification_flags_a_citation_to_a_fact_that_does_not_exist():
    report = verify_narrative("Margin held firm [F999].", _pack())
    assert "[F999]" in report[report["status"] == "UNSUPPORTED"]["figure"].tolist()


def test_verification_allows_calendar_years_and_month_counts():
    text = "Across 2024 and 2025 the 12 month view improved."
    report = verify_narrative(text, _pack())
    assert (report["status"] == "SUPPORTED").all()


def test_citation_identifiers_are_not_mistaken_for_claims():
    report = verify_narrative("Revenue was EUR 2,446.6m [F001].", _pack())
    # 001 must not be checked as though it were a stated figure.
    assert "001" not in report["figure"].tolist()


def test_evidence_pack_is_complete_and_identified(artifacts):
    ev = build_evidence(artifacts)
    frame = ev.frame()
    assert len(frame) > 40
    assert frame["fact_id"].is_unique
    assert frame["fact_id"].str.match(r"^F\d{3}$").all()
    categories = set(frame["category"])
    for expected in {"Group performance", "Product performance", "Forecast", "Scenarios"}:
        assert expected in categories


def test_deterministic_writer_produces_a_fully_traceable_narrative(artifacts):
    ev = build_evidence(artifacts)
    narrative = deterministic_narrative(artifacts, ev)
    report = verify_narrative(narrative, ev, context_block(artifacts))
    assert (report["status"] == "UNSUPPORTED").sum() == 0, \
        report[report["status"] == "UNSUPPORTED"].to_string(index=False)
    for section in ("## Executive summary", "## Forecast outlook", "## Scenario risk"):
        assert section in narrative


def test_insights_stage_falls_back_without_credentials(artifacts):
    result = generate_insights(artifacts, force_fallback=True)
    assert result.generator == "deterministic"
    assert result.unsupported_count == 0
    written = write_insights(artifacts, result)
    body = (artifacts.cfg.path("insights") / "market_commentary.md").read_text()
    assert "Traceability" in body
    assert pd.read_csv(written["evidence_pack"].split("/")[-1] if False
                       else artifacts.cfg.path("insights") / "evidence_pack.csv").shape[0] > 40
