"""AI-assisted analysis workflow.

The pipeline's quantitative work is finished before this module runs. Its job
is interpretation: reading the validated evidence pack and writing the
management commentary that connects the numbers to the market drivers behind
them.

Three properties keep this trustworthy:

1. **The model does no arithmetic.** It receives pre-computed facts and is
   instructed to restate them, never to derive new ones.
2. **Every figure is cited.** The model must tag each number with the fact id
   it came from, so a reader can trace any claim back to the calculation.
3. **The output is verified.** :func:`verify_narrative` re-reads the generated
   text, extracts every number in it and checks it against the evidence pack.
   Unsupported figures are reported, not silently published.

If no API credentials are configured the deterministic writer takes over, so
the pipeline always produces an insights document.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..pipeline import Artifacts
from .evidence import EvidenceBuilder, build_evidence, context_block

SYSTEM_PROMPT = """\
You are a senior market analyst in the international wholesale division of a \
European telecommunications group. You write the commentary that accompanies \
the monthly performance and forecast pack for the divisional management team.

You will be given (a) business context and (b) an evidence pack of pre-computed \
facts, each with a unique identifier. Follow these rules without exception:

1. Use ONLY numbers that appear in the evidence pack. Never calculate, derive, \
   sum, average or estimate a new figure - not even a simple difference.
2. Immediately after every number you state, cite its identifier in square \
   brackets, for example: "revenue reached EUR 2,446.6m [F001]".
3. If a point you want to make is not supported by the pack, either make it \
   qualitatively without numbers, or leave it out. Never guess.
4. Explain movements by connecting the facts to the structural market drivers \
   given in the context. Attribution should be argued, not asserted.
5. Write for readers who know the industry. Be specific and economical. No \
   filler, no restating the brief, no hedging language that carries no \
   information.
6. Distinguish clearly between what the data shows (actuals), what the model \
   projects (forecast) and what is an assumption (scenarios)."""

USER_TEMPLATE = """\
# Business context

{context}

# Evidence pack

{evidence}

# Task

Write the management commentary for this pack in Markdown, using exactly these \
sections:

## Executive summary
Three to four sentences: where the business landed, what drove it, and what the \
next twelve months look like.

## What drove the year
The material movements in the last twelve months versus the prior twelve. \
Cover the volume and price decomposition, the products that moved most, and the \
market indicators that explain them.

## Forecast outlook
What the model projects for the next twelve months and how much confidence the \
backtest evidence supports. State the accuracy comparison against the benchmark.

## Scenario risk
The planning range between the scenarios and which parts of the portfolio drive \
the spread.

## Where to focus
Three to five specific, actionable points for the commercial team. Each must be \
anchored to a cited fact.

## Watch items
Concentration, retention, single-account dependencies or anything else in the \
pack that represents a risk worth monitoring.

Target 700-900 words."""


@dataclass
class InsightsResult:
    narrative: str
    generator: str          # "claude" or "deterministic"
    model: str
    evidence: pd.DataFrame
    verification: pd.DataFrame
    note: str = ""

    @property
    def unsupported_count(self) -> int:
        if self.verification.empty:
            return 0
        return int((self.verification["status"] == "UNSUPPORTED").sum())


# ---------------------------------------------------------------------------
# Numeric verification
# ---------------------------------------------------------------------------
# Comma-grouped numbers first (so "2,446.6" is not split at the comma), then
# plain digit runs - ordered this way so a plain 4-digit number like "2024" is
# never chopped into "202" + "4" by the grouped alternative.
NUMBER_RE = re.compile(
    r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?"
)


def _numbers_in(text: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for match in NUMBER_RE.finditer(text):
        raw = match.group(0)
        try:
            found.append((raw, float(raw.replace(",", ""))))
        except ValueError:
            continue
    return found


def verify_narrative(narrative: str, evidence: EvidenceBuilder,
                     context: str = "", tolerance: float = 0.051) -> pd.DataFrame:
    """Check that every number in the narrative traces to the evidence pack.

    A figure is supported when it matches a fact value (at the precision the
    pack renders it), a number stated in the business context, a calendar year
    in the window, or a fact identifier. Anything else is flagged - which is
    exactly the case where a model has quietly done arithmetic of its own.
    """
    allowed: set[float] = set()
    for fact in evidence.facts:
        value = fact.value
        if value != value:  # NaN
            continue
        allowed.update({round(value, 1), round(value, 0), round(abs(value), 1),
                        round(abs(value), 0)})
    for _, value in _numbers_in(context):
        allowed.add(round(value, 1))
        allowed.add(round(value, 0))
    allowed.update(float(y) for y in range(2015, 2036))       # calendar years
    allowed.update(float(n) for n in range(1, 13))            # months / horizons

    fact_ids = {f.fact_id for f in evidence.facts}
    rows = []
    # Numbers inside a citation marker are identifiers, not claims.
    stripped = re.sub(r"\[F\d{3}\]", " ", narrative)

    for raw, value in _numbers_in(stripped):
        candidates = {round(value, 1), round(value, 0), round(abs(value), 1),
                      round(abs(value), 0)}
        supported = bool(candidates & allowed) or any(
            abs(value - a) <= tolerance for a in allowed if abs(a) < 1e7)
        rows.append({"figure": raw, "value": value,
                     "status": "SUPPORTED" if supported else "UNSUPPORTED"})

    report = pd.DataFrame(rows).drop_duplicates(subset=["figure"]) if rows else \
        pd.DataFrame(columns=["figure", "value", "status"])

    cited = set(re.findall(r"\[(F\d{3})\]", narrative))
    unknown = sorted(cited - fact_ids)
    for fid in unknown:
        report = pd.concat([report, pd.DataFrame(
            [{"figure": f"[{fid}]", "value": float("nan"),
              "status": "UNSUPPORTED"}])], ignore_index=True)

    report.attrs["citations_used"] = len(cited & fact_ids)
    return report.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------
def _credentials_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # `ant auth login` stores a profile the SDK picks up with no env var set.
    return (Path.home() / ".config" / "anthropic").exists()


def _call_claude(system: str, user: str, model: str, max_tokens: int,
                 effort: str = "medium") -> tuple[str, str]:
    """Call the Messages API. Returns ``(text, note)``; raises on failure."""
    import anthropic

    client = anthropic.Anthropic(timeout=180.0, max_retries=2)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        # Thinking is adaptive by default on current models; effort keeps the
        # reasoning depth proportionate to a bounded writing task. Sampling
        # parameters such as temperature are not accepted on these models.
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "") or ""
        raise RuntimeError(f"Model declined to answer: {detail}")

    text = "".join(block.text for block in response.content if block.type == "text")
    note = (f"model={response.model}, input_tokens={response.usage.input_tokens}, "
            f"output_tokens={response.usage.output_tokens}, "
            f"stop_reason={response.stop_reason}")
    if response.stop_reason == "max_tokens":
        note += " (response hit the token limit and may be truncated)"
    return text.strip(), note


# ---------------------------------------------------------------------------
# Deterministic fallback writer
# ---------------------------------------------------------------------------
def _lookup(ev: EvidenceBuilder, needle: str) -> tuple[str, float, str] | None:
    for fact in ev.facts:
        if needle.lower() in fact.statement.lower():
            return fact.fact_id, fact.value, fact.unit
    return None


def _cite(ev: EvidenceBuilder, needle: str, fmt: str = "{v:,.1f}",
          suffix: str = "") -> str:
    """Render a fact as ``value+unit [id]`` so the citation follows the unit."""
    hit = _lookup(ev, needle)
    if hit is None:
        return "n/a"
    fid, value, _ = hit
    return f"{fmt.format(v=value)}{suffix} [{fid}]"


def deterministic_narrative(art: Artifacts, ev: EvidenceBuilder) -> str:
    """Rule-based commentary used when no model credentials are configured.

    Deliberately templated: it says less than the model does, but every
    sentence is generated from the same evidence pack, so the pipeline never
    depends on an external service to produce a complete deliverable.
    """
    facts = {f.fact_id: f for f in ev.facts}
    prod = [f for f in ev.facts if f.category == "Product performance"
            and "growth year on year" in f.statement]
    growers = sorted([f for f in prod if f.value == f.value],
                     key=lambda f: f.value, reverse=True)
    top = growers[0] if growers else None
    bottom = growers[-1] if growers else None

    bridge_vol = _lookup(ev, "Total volume effect")
    bridge_price = _lookup(ev, "Total price effect")

    lines = [
        "## Executive summary",
        "",
        f"Revenue over the last twelve months was "
        f"EUR {_cite(ev, 'Revenue, last 12 months', suffix='m')}, "
        f"{_cite(ev, 'Revenue growth year on year', suffix='%')} above the prior twelve "
        f"months, at a gross margin of "
        f"{_cite(ev, 'Gross margin percentage, last 12 months', suffix='%')} "
        f"({_cite(ev, 'Gross margin percentage change year on year', '{v:+.1f}', 'pp')} "
        f"year on year). Across the full observation window revenue has compounded at "
        f"{_cite(ev, 'Revenue CAGR', suffix='%')} a year. The champion forecast projects "
        f"EUR {_cite(ev, 'Forecast revenue, next 12 months', suffix='m')} for the next "
        f"twelve months, "
        f"{_cite(ev, 'Forecast revenue growth versus the last 12 months', suffix='%')} "
        f"above the trailing year.",
        "",
        "## What drove the year",
        "",
    ]

    if bridge_vol and bridge_price:
        lines.append(
            f"The year-on-year movement is a volume story offset by continued rate erosion: "
            f"traffic growth contributed EUR {bridge_vol[1]:,.1f}m [{bridge_vol[0]}] while "
            f"price movements took EUR {abs(bridge_price[1]):,.1f}m [{bridge_price[0]}] out "
            f"of revenue. That pattern is characteristic of a wholesale portfolio in which "
            f"capacity and roaming volumes are growing faster than realised prices are falling."
        )
        lines.append("")

    if top and bottom:
        lines.append(
            f"The strongest product movement was {top.statement.replace(' revenue growth year on year', '')} "
            f"at {top.value:+.1f}% [{top.fact_id}]; the weakest was "
            f"{bottom.statement.replace(' revenue growth year on year', '')} at "
            f"{bottom.value:+.1f}% [{bottom.fact_id}]. Voice termination continues to be "
            f"eroded by OTT substitution, while messaging and roaming benefit from "
            f"e-commerce activity and the recovery in international travel."
        )
        lines.append("")

    lines += [
        "## Forecast outlook",
        "",
        f"The selected model is {art.meta['champion_model']}, chosen on rolling-origin "
        f"backtest accuracy across {len(art.meta['backtest_origins'])} forecast origins. "
        f"It records a WAPE of "
        f"{_cite(ev, 'Champion model backtest WAPE', suffix='%')} against "
        f"{_cite(ev, 'Seasonal-naive benchmark backtest WAPE', suffix='%')} for the "
        f"seasonal-naive benchmark, an improvement of "
        f"{_cite(ev, 'Champion accuracy improvement over the benchmark', suffix='%')}. "
        f"Error widens with horizon, from "
        f"{_cite(ev, 'Backtest WAPE at a 1-month horizon', suffix='%')} at one month to "
        f"{_cite(ev, 'Backtest WAPE at a 12-month horizon', suffix='%')} at twelve, which "
        f"is the basis for the widening prediction interval in the pack.",
        "",
        "## Scenario risk",
        "",
        f"The scenario set spans "
        f"EUR {_cite(ev, 'Downside scenario revenue', suffix='m')} to "
        f"EUR {_cite(ev, 'Upside scenario revenue', suffix='m')} against a baseline of "
        f"EUR {_cite(ev, 'Baseline scenario revenue', suffix='m')} - a planning range of "
        f"EUR {_cite(ev, 'Planning range between the upside', suffix='m')}, or "
        f"{_cite(ev, 'Planning range as a share of the baseline', suffix='%')} of the "
        f"baseline. "
        f"The spread is driven by the growth products, where the assumed price and "
        f"volume adjustments compound over the horizon.",
        "",
        "## Where to focus",
        "",
        f"- Defend realised price where volume growth is strongest: the price effect of "
        f"EUR {abs(bridge_price[1]):,.1f}m [{bridge_price[0]}] is the single largest drag "
        f"on the year." if bridge_price else "- Defend realised price in the growth products.",
        f"- Manage the voice decline for margin rather than volume; it is the only product "
        f"family in structural contraction.",
        f"- Protect the account base: the ten largest accounts carry "
        f"{_cite(ev, 'Share of revenue from the ten largest accounts', suffix='%')} "
        f"of revenue.",
        "",
        "## Watch items",
        "",
        f"- Customer concentration: top-10 share of "
        f"{_cite(ev, 'Share of revenue from the ten largest accounts', suffix='%')} and an "
        f"HHI of {_cite(ev, 'Herfindahl')}.",
        f"- Net revenue retention stands at "
        f"{_cite(ev, 'Net revenue retention', suffix='%')}, with "
        f"{_cite(ev, 'Accounts that churned', '{v:,.0f}')} accounts churned during the "
        f"window.",
        "- Forecast error is measured, not assumed: re-run the backtest each month and "
        "watch for bias drifting away from zero.",
    ]
    _ = facts
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def generate_insights(art: Artifacts, force_fallback: bool = False) -> InsightsResult:
    cfg = art.cfg
    ai_cfg = cfg.ai
    ev = build_evidence(art)
    context = context_block(art)
    user_prompt = USER_TEMPLATE.format(context=context, evidence=ev.as_text())

    generator, model, note = "deterministic", "-", ""
    narrative = ""

    want_ai = bool(ai_cfg.get("enabled", True)) and not force_fallback
    if want_ai and not _credentials_available():
        note = ("No Anthropic credentials found - used the deterministic writer. "
                "Set ANTHROPIC_API_KEY or run 'ant auth login' for the model-written "
                "commentary.")
    elif want_ai:
        try:
            narrative, note = _call_claude(
                SYSTEM_PROMPT, user_prompt,
                model=str(ai_cfg.get("model", "claude-opus-5")),
                max_tokens=int(ai_cfg.get("max_tokens", 8000)),
                effort=str(ai_cfg.get("effort", "medium")),
            )
            generator = "claude"
            model = str(ai_cfg.get("model", "claude-opus-5"))
        except Exception as exc:  # noqa: BLE001 - any failure must not break the pipeline
            note = f"Model call failed ({type(exc).__name__}: {exc}); used the deterministic writer."
            narrative = ""

    if not narrative:
        narrative = deterministic_narrative(art, ev)
        generator = "deterministic"

    verification = verify_narrative(narrative, ev, context)
    return InsightsResult(narrative=narrative, generator=generator, model=model,
                          evidence=ev.frame(), verification=verification, note=note)


def write_insights(art: Artifacts, result: InsightsResult) -> dict[str, str]:
    """Persist the commentary, its evidence pack and the verification report."""
    out = art.cfg.path("insights")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header = [
        f"# {art.cfg.project['name']} - market commentary",
        "",
        f"*Actuals to {art.meta['history_end']}. Forecast to "
        f"{art.cfg.forecast_months[-1]}. Generated {stamp}.*",
        "",
        f"*Written by: {'Claude (' + result.model + ')' if result.generator == 'claude' else 'deterministic rule-based writer'}. "
        f"Every figure is drawn from a validated evidence pack of "
        f"{len(result.evidence)} pre-computed facts; the model performs no arithmetic.*",
        "",
    ]
    if result.note:
        header += [f"> Note: {result.note}", ""]

    checked = len(result.verification)
    footer = [
        "",
        "---",
        "",
        "## Traceability",
        "",
        f"- Figures checked against the evidence pack: {checked}",
        f"- Figures not traceable to a fact: {result.unsupported_count}",
        f"- Distinct facts cited: {result.verification.attrs.get('citations_used', 0)}",
        "- Full evidence pack: `evidence_pack.csv`. Verification detail: "
        "`verification_report.csv`.",
    ]

    doc = "\n".join(header) + "\n" + result.narrative + "\n" + "\n".join(footer) + "\n"
    (out / "market_commentary.md").write_text(doc, encoding="utf-8")
    result.evidence.to_csv(out / "evidence_pack.csv", index=False)
    result.verification.to_csv(out / "verification_report.csv", index=False)

    root = art.cfg.root
    return {
        "commentary": str((out / "market_commentary.md").relative_to(root)),
        "evidence_pack": str((out / "evidence_pack.csv").relative_to(root)),
        "verification": str((out / "verification_report.csv").relative_to(root)),
    }
