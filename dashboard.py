#!/usr/bin/env python3
"""Comprehensive TAO subnet investment dashboard (Streamlit).

Run:
  streamlit run dashboard.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from tao_subnet_analysis import (
    AnalysisConfig,
    SubnetScore,
    load_env_file,
    load_subnets_from_file,
    load_subnets_from_taostats,
    pick_undervalued,
    score_subnets,
)

st.set_page_config(page_title="TAO Subnet Dashboard", layout="wide")


def scores_to_df(scores: list[SubnetScore]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "NetUID": s.netuid,
                "Name": s.name,
                "Overall": s.overall_score,
                "Valuation": s.valuation_score,
                "Quality": s.quality_score,
                "Momentum": s.momentum_score,
                "Market Cap": s.market_cap,
                "Annualized Revenue": s.annualized_revenue,
                "Daily Emission": s.daily_emission,
                "TAO Locked": s.tao_locked,
                "Active Validators": s.active_validators,
                "Active Miners": s.active_miners,
                "MCap/Rev": s.cap_to_rev,
                "MCap/Emission": s.cap_to_emission,
                "Growth 30d": s.growth_30d,
                "Alpha Trend 30d": s.alpha_trend_30d,
            }
            for s in scores
        ]
    )


def _normalize_weights(value_w: float, quality_w: float, momentum_w: float) -> tuple[float, float, float]:
    total = value_w + quality_w + momentum_w
    if total <= 0:
        return 0.45, 0.30, 0.25
    return value_w / total, quality_w / total, momentum_w / total


@st.cache_data(ttl=300, show_spinner=False)
def fetch_rows_from_taostats(api_key: str, limit: int) -> list[dict]:
    return load_subnets_from_taostats(api_key=api_key, limit=limit)


@st.cache_data(show_spinner=False)
def fetch_rows_from_json(path_str: str) -> list[dict]:
    return load_subnets_from_file(Path(path_str))


def render_overview(df: pd.DataFrame, undervalued_df: pd.DataFrame) -> None:
    st.subheader("Market Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Subnets analyzed", f"{len(df)}")
    m2.metric("Median MCap/Rev", f"{df['MCap/Rev'].median():.2f}x")
    m3.metric("Median MCap/Emission", f"{df['MCap/Emission'].median():.2f}x")
    m4.metric("Undervalued count", f"{len(undervalued_df)}")

    st.markdown("### Score Distribution")
    st.bar_chart(df.set_index("Name")[["Overall", "Valuation", "Quality", "Momentum"]])


def render_rankings(df: pd.DataFrame) -> None:
    st.subheader("Ranked Subnets")
    sort_col = st.selectbox("Sort by", ["Overall", "Valuation", "Quality", "Momentum"], index=0)
    ascending = st.checkbox("Ascending order", value=False)

    display_cols = [
        "NetUID",
        "Name",
        "Overall",
        "Valuation",
        "Quality",
        "Momentum",
        "MCap/Rev",
        "MCap/Emission",
        "Active Validators",
        "Active Miners",
    ]
    ranked = df.sort_values(by=sort_col, ascending=ascending).reset_index(drop=True)
    ranked.insert(0, "Rank", ranked.index + 1)
    st.dataframe(ranked[["Rank"] + display_cols], use_container_width=True)

    st.download_button(
        "Download ranked table (CSV)",
        ranked.to_csv(index=False).encode("utf-8"),
        file_name="tao_ranked_subnets.csv",
        mime="text/csv",
    )


def render_undervalued(undervalued_df: pd.DataFrame) -> None:
    st.subheader("Undervalued Candidates")
    if undervalued_df.empty:
        st.info("No subnets passed the current undervaluation thresholds.")
        return

    st.success(f"{len(undervalued_df)} subnet(s) pass your thresholds.")
    st.dataframe(
        undervalued_df[
            [
                "NetUID",
                "Name",
                "Overall",
                "Valuation",
                "Quality",
                "Momentum",
                "MCap/Rev",
                "MCap/Emission",
            ]
        ].sort_values("Overall", ascending=False),
        use_container_width=True,
    )

    scatter_df = undervalued_df.copy()
    st.markdown("### Risk/Reward View")
    st.scatter_chart(
        scatter_df,
        x="Valuation",
        y="Momentum",
        size="Overall",
        color="Quality",
    )


def render_scenario_analysis(rows: list[dict]) -> None:
    st.subheader("Scenario Analysis")
    st.caption("Use this to test how rankings shift when your factor preference changes.")

    c1, c2, c3 = st.columns(3)
    with c1:
        scenario_value = st.slider("Scenario Value Weight", 0.0, 1.0, 0.45, 0.01, key="sc_value")
    with c2:
        scenario_quality = st.slider("Scenario Quality Weight", 0.0, 1.0, 0.30, 0.01, key="sc_quality")
    with c3:
        scenario_momentum = st.slider("Scenario Momentum Weight", 0.0, 1.0, 0.25, 0.01, key="sc_momentum")

    v, q, m = _normalize_weights(scenario_value, scenario_quality, scenario_momentum)
    scenario_config = AnalysisConfig(value_weight=v, quality_weight=q, momentum_weight=m)
    scenario_scores = score_subnets(rows, scenario_config)
    scenario_df = scores_to_df(scenario_scores)

    st.write(f"Normalized weights → Value: `{v:.2f}` | Quality: `{q:.2f}` | Momentum: `{m:.2f}`")
    st.dataframe(
        scenario_df[["NetUID", "Name", "Overall", "Valuation", "Quality", "Momentum"]],
        use_container_width=True,
    )


def render_raw_data(rows: list[dict]) -> None:
    st.subheader("Raw Data Explorer")
    raw_df = pd.DataFrame(rows)
    st.dataframe(raw_df, use_container_width=True)

    st.download_button(
        "Download raw data (JSON)",
        raw_df.to_json(orient="records", indent=2).encode("utf-8"),
        file_name="tao_subnets_raw.json",
        mime="application/json",
    )


def main() -> None:
    st.title("TAO Subnet Comprehensive Investment Dashboard")
    st.caption("Live + offline subnet analytics for valuation, quality, momentum, and undervaluation screening.")

    with st.sidebar:
        st.header("Data Source")
        source = st.radio("Choose source", ["Taostats API", "Local JSON"], index=0)

        env_file = st.text_input("Env file", value=".env")
        load_env_file(Path(env_file))

        if source == "Taostats API":
            api_key = st.text_input(
                "Taostats API key",
                type="password",
                value=os.getenv("TAOSTATS_API_KEY", ""),
                help="Key is not stored by this app.",
            )
            taostats_limit = st.number_input("Taostats row limit", min_value=20, max_value=500, value=200)
        else:
            api_key = ""
            taostats_limit = 200

            json_path = st.text_input("JSON file path", value="data/subnets_sample.json")

        st.header("Filters & Weights")
        min_overall = st.slider("Min Overall Score", 0.0, 1.0, 0.60, 0.01)
        min_valuation = st.slider("Min Valuation Score", 0.0, 1.0, 0.55, 0.01)

        value_weight = st.slider("Value Weight", 0.0, 1.0, 0.45, 0.01)
        quality_weight = st.slider("Quality Weight", 0.0, 1.0, 0.30, 0.01)
        momentum_weight = st.slider("Momentum Weight", 0.0, 1.0, 0.25, 0.01)

        v, q, m = _normalize_weights(value_weight, quality_weight, momentum_weight)
        st.caption(f"Normalized Weights: Value={v:.2f}, Quality={q:.2f}, Momentum={m:.2f}")

    try:
        if source == "Taostats API":
            if not api_key:
                st.warning("Enter your Taostats API key in the sidebar to load live data.")
                st.stop()
            rows = fetch_rows_from_taostats(api_key=api_key, limit=int(taostats_limit))
            source_label = "Taostats API"
        else:
            rows = fetch_rows_from_json(json_path)
            source_label = json_path
    except Exception as exc:
        st.error(f"Failed to load data: {exc}")
        st.stop()

    config = AnalysisConfig(
        value_weight=v,
        quality_weight=q,
        momentum_weight=m,
        min_overall_score=min_overall,
        min_valuation_score=min_valuation,
    )

    scores = score_subnets(rows, config)
    undervalued = pick_undervalued(scores, config)

    df = scores_to_df(scores)
    undervalued_df = scores_to_df(undervalued)

    st.markdown(f"**Active data source:** `{source_label}`")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Overview",
            "Rankings",
            "Undervalued",
            "Scenario Analysis",
            "Raw Data",
        ]
    )

    with tab1:
        render_overview(df, undervalued_df)
    with tab2:
        render_rankings(df)
    with tab3:
        render_undervalued(undervalued_df)
    with tab4:
        render_scenario_analysis(rows)
    with tab5:
        render_raw_data(rows)


if __name__ == "__main__":
    main()
