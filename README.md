# TAO Subnet Analysis Toolkit

A practical toolkit for analyzing Bittensor (TAO) subnets and flagging potentially undervalued opportunities.

## What it does

- Supports **live Taostats API ingestion** (with your API key) and local JSON ingestion.
- Computes valuation, quality, and momentum factors.
- Produces:
  - a ranked table of subnets
  - an "undervalued candidates" list based on configurable thresholds
  - overall market diagnostics to support investment decisions

## Why this helps investment decisions

The model combines three dimensions:

1. **Valuation** (cheap vs expensive)
   - Market Cap / Annualized Revenue Proxy
   - Market Cap / Emission Proxy
2. **Quality / Sustainability**
   - Active validator participation
   - Active miner participation
   - TAO/alpha locked proxy
3. **Momentum**
   - 30-day trend proxy
   - short-medium trend blend

A subnet is considered attractive when valuation is low *relative to peers* while quality and momentum remain healthy.

## Data source options

### Option A) Live Taostats API (recommended)

Set your API key and run:

```bash
export TAOSTATS_API_KEY="your_api_key_here"
python3 tao_subnet_analysis.py \
  --use-taostats-api \
  --output reports/live_report.md
```

Create a local `.env` (do not commit) from the example:

```bash
cp .env.example .env
# then edit .env and set TAOSTATS_API_KEY
```

The CLI auto-loads `.env` by default, so this also works:

```bash
python3 tao_subnet_analysis.py \
  --use-taostats-api \
  --output reports/live_report.md
```

Or pass key directly:

```bash
python3 tao_subnet_analysis.py \
  --use-taostats-api \
  --taostats-api-key "your_api_key_here" \
  --output reports/live_report.md
```

### Option B) Local JSON file

```bash
python3 tao_subnet_analysis.py \
  --input data/subnets_sample.json \
  --output reports/sample_report.md
```

## Threshold tuning

```bash
python3 tao_subnet_analysis.py \
  --use-taostats-api \
  --output reports/live_report.md \
  --min-overall-score 0.60 \
  --min-valuation-score 0.55
```

- `min-overall-score`: minimum composite attractiveness score.
- `min-valuation-score`: minimum valuation score (higher = cheaper).

## Input format (local JSON mode)

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

## Output

The generated Markdown report includes:

- **Market overview** (median valuation and participation)
- **Top ranked subnets** by overall score
- **Undervalued candidates** meeting your thresholds
- **Per-subnet diagnostics** with ratios and normalized factors

## Notes

- This is a **decision-support** tool, not financial advice.
- In Taostats mode, some fields are model proxies derived from available API endpoints.
- `.env` is ignored by git; use `.env.example` as your template.
- You can adjust weights in `AnalysisConfig` inside `tao_subnet_analysis.py`.


## Comprehensive Dashboard

If you want a full interactive dashboard (filters, ranking tables, undervalued list, scenario analysis, and raw data explorer), run:

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

Dashboard features:
- Live Taostats API mode and local JSON mode
- Adjustable thresholds (`min overall`, `min valuation`)
- Adjustable factor weights (value/quality/momentum)
- Multi-tab UI: Overview, Rankings, Undervalued, Scenario Analysis, Raw Data
- CSV/JSON export for ranked and raw datasets

