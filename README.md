# TAO Subnet Analysis Toolkit

A lightweight toolkit for analyzing Bittensor (TAO) subnets and flagging potentially undervalued opportunities.

## What it does

- Ingests subnet metrics from a JSON file.
- Computes valuation, quality, and momentum factors.
- Produces:
  - a ranked table of subnets
  - an "undervalued candidates" list based on configurable thresholds
  - overall market-level diagnostics to support investment decisions

## Why this helps investment decisions

The model combines three dimensions:

1. **Valuation** (cheap vs expensive)
   - Market Cap / Annualized Revenue
   - Market Cap / Emission
2. **Quality / Sustainability**
   - Validator decentralization
   - Miner participation
   - TAO locked (economic security)
3. **Momentum**
   - 30-day growth
   - 30-day alpha trend

A subnet is considered attractive when valuation is low *relative to peers* while quality and momentum remain healthy.

## Input format

Input is a JSON array of subnet objects. Example fields:

```json
[
  {
    "netuid": 1,
    "name": "Text Inference",
    "market_cap": 15000000,
    "daily_revenue": 9000,
    "daily_emission": 3800,
    "tao_locked": 120000,
    "active_validators": 48,
    "active_miners": 320,
    "growth_30d": 0.18,
    "alpha_trend_30d": 0.11
  }
]
```

See `data/subnets_sample.json` for a complete example.

## Quick start

```bash
python3 tao_subnet_analysis.py \
  --input data/subnets_sample.json \
  --output reports/sample_report.md
```

### Optional thresholds

```bash
python3 tao_subnet_analysis.py \
  --input data/subnets_sample.json \
  --output reports/sample_report.md \
  --min-overall-score 0.60 \
  --min-valuation-score 0.55
```

- `min-overall-score`: minimum composite attractiveness score.
- `min-valuation-score`: minimum valuation score (higher = cheaper).

## Output

The generated Markdown report includes:

- **Market overview** (median valuation and participation)
- **Top ranked subnets** by overall score
- **Undervalued candidates** meeting your thresholds
- **Per-subnet diagnostics** with ratios and normalized factors

## Notes

- This is a **decision-support** tool, not financial advice.
- Replace sample data with your own pipeline from TAO ecosystem sources.
- You can adjust weights in `AnalysisConfig` inside `tao_subnet_analysis.py`.
