#!/usr/bin/env python3
"""TAO subnet analysis and undervaluation screener.

Supports two data sources:
1) Local JSON via --input
2) Live Taostats API via --use-taostats-api and API key
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EPS = 1e-9
TAOSTATS_BASE_URL = "https://api.taostats.io"


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def taostats_get(
    path: str,
    api_key: str,
    query: dict[str, Any] | None = None,
    timeout: int = 20,
) -> Any:
    url = f"{TAOSTATS_BASE_URL}{path}"
    if query:
        url += f"?{urlencode(query)}"

    req = Request(
        url,
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "tao-subnet-analysis/1.0",
        },
        method="GET",
    )

    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_subnets_from_taostats(api_key: str, limit: int = 200) -> list[dict[str, Any]]:
    pools_raw = taostats_get("/api/dtao/pool/latest/v1", api_key, {"limit": limit})
    subnets_raw = taostats_get("/api/subnet/latest/v1", api_key, {"limit": limit})
    identity_raw = taostats_get("/api/subnet/identity/v1", api_key, {"limit": limit})

    if not isinstance(pools_raw, list) or not isinstance(subnets_raw, list):
        raise ValueError("Unexpected Taostats API response format")

    pools_by_netuid = {int(p.get("netuid")): p for p in pools_raw if p.get("netuid") is not None}
    subnet_by_netuid = {
        int(s.get("netuid")): s for s in subnets_raw if s.get("netuid") is not None
    }

    names_by_netuid: dict[int, str] = {}
    if isinstance(identity_raw, list):
        for item in identity_raw:
            netuid = item.get("netuid")
            if netuid is None:
                continue
            label = item.get("subnet_name") or item.get("name") or f"Subnet {netuid}"
            names_by_netuid[int(netuid)] = str(label)

    rows: list[dict[str, Any]] = []
    common_netuids = sorted(set(pools_by_netuid).intersection(subnet_by_netuid))
    for netuid in common_netuids:
        pool = pools_by_netuid[netuid]
        subnet = subnet_by_netuid[netuid]

        # Fields sourced from Taostats endpoints:
        # - market_cap, alpha_staked, tao_volume_24_hr, price_change_1_month from pool/latest
        # - active_validators, active_miners, emission from subnet/latest
        # Notes:
        # - tao_volume_24_hr is used as a practical revenue proxy.
        # - emission is used as a relative dilution pressure proxy.
        rows.append(
            {
                "netuid": netuid,
                "name": names_by_netuid.get(netuid, f"Subnet {netuid}"),
                "market_cap": _safe_float(pool.get("market_cap")),
                "daily_revenue": _safe_float(pool.get("tao_volume_24_hr")),
                "daily_emission": _safe_float(subnet.get("emission"), 1.0),
                "tao_locked": _safe_float(pool.get("alpha_staked")),
                "active_validators": int(_safe_float(subnet.get("active_validators"), 0.0)),
                "active_miners": int(_safe_float(subnet.get("active_miners"), 0.0)),
                # Use monthly price change as growth signal.
                "growth_30d": _safe_float(pool.get("price_change_1_month")) / 100.0,
                # Use 24h and 1w blended trend as short-medium alpha trend proxy.
                "alpha_trend_30d": (
                    0.35 * (_safe_float(pool.get("price_change_1_day")) / 100.0)
                    + 0.65 * (_safe_float(pool.get("price_change_1_week")) / 100.0)
                ),
            }
        )

    if not rows:
        raise ValueError("No subnet rows could be built from Taostats API responses")

    return rows


def load_subnets_from_file(path: Path) -> list[dict[str, Any]]:
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


def write_report(
    scores: list[SubnetScore],
    undervalued: list[SubnetScore],
    output: Path,
    source_label: str,
) -> None:
    cap_to_rev_vals = [s.cap_to_rev for s in scores]
    cap_to_emission_vals = [s.cap_to_emission for s in scores]
    validators = [s.active_validators for s in scores]
    miners = [s.active_miners for s in scores]

    lines = [
        "# TAO Subnet Investment Report",
        "",
        f"Data source: **{source_label}**",
        "",
        "## Market Overview",
        f"- Subnets analyzed: **{len(scores)}**",
        f"- Median Market Cap / Revenue Proxy: **{median(cap_to_rev_vals):.2f}x**",
        f"- Median Market Cap / Emission Proxy: **{median(cap_to_emission_vals):.2f}x**",
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
            "- Higher **Momentum score** means stronger trend in pool pricing.",
            "- This is a model-based screener and should be paired with qualitative DD.",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TAO subnet undervaluation analysis")
    p.add_argument("--input", type=Path, help="Path to subnet JSON file")
    p.add_argument("--output", type=Path, required=True, help="Path to markdown report output")
    p.add_argument("--use-taostats-api", action="store_true", help="Load live subnet data from Taostats")
    p.add_argument("--taostats-api-key", help="Taostats API key (or set TAOSTATS_API_KEY)")
    p.add_argument("--taostats-limit", type=int, default=200, help="Taostats API page size")
    p.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional dotenv file (default: .env)")
    p.add_argument("--min-overall-score", type=float, default=0.60)
    p.add_argument("--min-valuation-score", type=float, default=0.55)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = AnalysisConfig(
        min_overall_score=args.min_overall_score,
        min_valuation_score=args.min_valuation_score,
    )

    if args.use_taostats_api:
        load_env_file(args.env_file)
        api_key = args.taostats_api_key or os.getenv("TAOSTATS_API_KEY")
        if not api_key:
            raise ValueError("Taostats API key required. Use --taostats-api-key or TAOSTATS_API_KEY")
        rows = load_subnets_from_taostats(api_key=api_key, limit=args.taostats_limit)
        source_label = "Taostats API"
    else:
        if not args.input:
            raise ValueError("--input is required unless --use-taostats-api is set")
        rows = load_subnets_from_file(args.input)
        source_label = str(args.input)

    scores = score_subnets(rows, config)
    undervalued = pick_undervalued(scores, config)
    write_report(scores, undervalued, args.output, source_label)

    print(f"Report written to: {args.output}")
    print(f"Data source: {source_label}")
    print(f"Subnets analyzed: {len(scores)}")
    print(f"Undervalued candidates: {len(undervalued)}")


if __name__ == "__main__":
    main()
