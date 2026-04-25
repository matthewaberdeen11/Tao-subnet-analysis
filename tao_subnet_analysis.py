#!/usr/bin/env python3
"""TAO subnet analysis and undervaluation screener."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

EPS = 1e-9


@dataclass
class AnalysisConfig:
    value_weight: float = 0.45
    quality_weight: float = 0.30
    momentum_weight: float = 0.25
    min_overall_score: float = 0.60
    min_valuation_score: float = 0.55


@dataclass
class SubnetScore:
    netuid: int
    name: str
    market_cap: float
    annualized_revenue: float
    daily_emission: float
    tao_locked: float
    active_validators: int
    active_miners: int
    growth_30d: float
    alpha_trend_30d: float
    cap_to_rev: float
    cap_to_emission: float
    valuation_score: float
    quality_score: float
    momentum_score: float
    overall_score: float


def _normalize(values: list[float], invert: bool = False) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < EPS:
        return [0.5 for _ in values]

    def scale(v: float) -> float:
        scaled = (v - lo) / (hi - lo)
        return 1.0 - scaled if invert else scaled

    return [scale(v) for v in values]


def _require_fields(record: dict[str, Any], fields: list[str]) -> None:
    missing = [f for f in fields if f not in record]
    if missing:
        raise ValueError(f"Subnet {record.get('netuid', '?')} missing fields: {missing}")


def load_subnets(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list) or not raw:
        raise ValueError("Input JSON must be a non-empty array of subnet objects")

    required = [
        "netuid",
        "name",
        "market_cap",
        "daily_revenue",
        "daily_emission",
        "tao_locked",
        "active_validators",
        "active_miners",
        "growth_30d",
        "alpha_trend_30d",
    ]
    for row in raw:
        _require_fields(row, required)
    return raw


def score_subnets(rows: list[dict[str, Any]], config: AnalysisConfig) -> list[SubnetScore]:
    annualized_revenue = [max(float(r["daily_revenue"]) * 365.0, EPS) for r in rows]
    cap_to_rev = [float(r["market_cap"]) / rev for r, rev in zip(rows, annualized_revenue)]
    cap_to_emission = [float(r["market_cap"]) / max(float(r["daily_emission"]), EPS) for r in rows]

    valuation_component = [0.6 * a + 0.4 * b for a, b in zip(cap_to_rev, cap_to_emission)]
    valuation_score = _normalize(valuation_component, invert=True)

    validator_score = _normalize([float(r["active_validators"]) for r in rows])
    miner_score = _normalize([float(r["active_miners"]) for r in rows])
    locked_score = _normalize([float(r["tao_locked"]) for r in rows])
    quality_score = [
        0.35 * v + 0.25 * m + 0.40 * l
        for v, m, l in zip(validator_score, miner_score, locked_score)
    ]

    growth_score = _normalize([float(r["growth_30d"]) for r in rows])
    alpha_score = _normalize([float(r["alpha_trend_30d"]) for r in rows])
    momentum_score = [0.5 * g + 0.5 * a for g, a in zip(growth_score, alpha_score)]

    scored: list[SubnetScore] = []
    for i, row in enumerate(rows):
        overall = (
            config.value_weight * valuation_score[i]
            + config.quality_weight * quality_score[i]
            + config.momentum_weight * momentum_score[i]
        )
        scored.append(
            SubnetScore(
                netuid=int(row["netuid"]),
                name=str(row["name"]),
                market_cap=float(row["market_cap"]),
                annualized_revenue=annualized_revenue[i],
                daily_emission=float(row["daily_emission"]),
                tao_locked=float(row["tao_locked"]),
                active_validators=int(row["active_validators"]),
                active_miners=int(row["active_miners"]),
                growth_30d=float(row["growth_30d"]),
                alpha_trend_30d=float(row["alpha_trend_30d"]),
                cap_to_rev=cap_to_rev[i],
                cap_to_emission=cap_to_emission[i],
                valuation_score=valuation_score[i],
                quality_score=quality_score[i],
                momentum_score=momentum_score[i],
                overall_score=overall,
            )
        )

    return sorted(scored, key=lambda s: s.overall_score, reverse=True)


def pick_undervalued(scores: list[SubnetScore], config: AnalysisConfig) -> list[SubnetScore]:
    return [
        s
        for s in scores
        if s.overall_score >= config.min_overall_score
        and s.valuation_score >= config.min_valuation_score
    ]


def write_report(scores: list[SubnetScore], undervalued: list[SubnetScore], output: Path) -> None:
    cap_to_rev_vals = [s.cap_to_rev for s in scores]
    cap_to_emission_vals = [s.cap_to_emission for s in scores]
    validators = [s.active_validators for s in scores]
    miners = [s.active_miners for s in scores]

    lines = [
        "# TAO Subnet Investment Report",
        "",
        "## Market Overview",
        f"- Subnets analyzed: **{len(scores)}**",
        f"- Median Market Cap / Revenue: **{median(cap_to_rev_vals):.2f}x**",
        f"- Median Market Cap / Daily Emission: **{median(cap_to_emission_vals):.2f}x**",
        f"- Median active validators: **{median(validators):.0f}**",
        f"- Median active miners: **{median(miners):.0f}**",
        "",
        "## Ranked Subnets (Best Overall First)",
        "",
        "| Rank | NetUID | Name | Overall | Valuation | Quality | Momentum | MCap/Rev | MCap/Emission |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]

    for idx, s in enumerate(scores, start=1):
        lines.append(
            f"| {idx} | {s.netuid} | {s.name} | {s.overall_score:.3f} | {s.valuation_score:.3f} | "
            f"{s.quality_score:.3f} | {s.momentum_score:.3f} | {s.cap_to_rev:.2f}x | {s.cap_to_emission:.2f}x |"
        )

    lines.extend(["", "## Undervalued Candidates", ""])
    if undervalued:
        lines.append("These subnets pass both overall quality and valuation thresholds.")
        lines.append("")
        for s in undervalued:
            lines.append(
                f"- **NetUID {s.netuid} ({s.name})** — Overall `{s.overall_score:.3f}`, "
                f"Valuation `{s.valuation_score:.3f}`, Quality `{s.quality_score:.3f}`, "
                f"Momentum `{s.momentum_score:.3f}`"
            )
    else:
        lines.append("No subnets currently passed your undervaluation filter thresholds.")

    lines.extend(
        [
            "",
            "## Interpretation Guide",
            "- Higher **Valuation score** means cheaper relative pricing vs peers.",
            "- Higher **Quality score** means stronger participation/security profile.",
            "- Higher **Momentum score** means stronger recent trend and growth.",
            "- Prioritize names that are cheap *and* maintain quality/momentum.",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TAO subnet undervaluation analysis")
    p.add_argument("--input", type=Path, required=True, help="Path to subnet JSON file")
    p.add_argument("--output", type=Path, required=True, help="Path to markdown report output")
    p.add_argument("--min-overall-score", type=float, default=0.60)
    p.add_argument("--min-valuation-score", type=float, default=0.55)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = AnalysisConfig(
        min_overall_score=args.min_overall_score,
        min_valuation_score=args.min_valuation_score,
    )

    rows = load_subnets(args.input)
    scores = score_subnets(rows, config)
    undervalued = pick_undervalued(scores, config)
    write_report(scores, undervalued, args.output)

    print(f"Report written to: {args.output}")
    print(f"Subnets analyzed: {len(scores)}")
    print(f"Undervalued candidates: {len(undervalued)}")


if __name__ == "__main__":
    main()
