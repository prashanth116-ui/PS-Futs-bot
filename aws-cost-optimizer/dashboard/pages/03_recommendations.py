"""Recommendations page for the dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Recommendations", page_icon="💡", layout="wide")

st.title("Rightsizing Recommendations")


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to view recommendations.")
    st.stop()

# Filter to servers with recommendations
if "recommended_type" not in df.columns:
    st.warning("No recommendation data available in this report.")
    st.stop()

recs_df = df[df["recommended_type"].notna()].copy()

if len(recs_df) == 0:
    st.success("All servers are appropriately sized! No recommendations needed.")
    st.stop()

# Sidebar filters
st.sidebar.header("Filters")

# Risk level filter
if "risk_level" in recs_df.columns:
    risk_levels = st.sidebar.multiselect(
        "Risk Level",
        options=recs_df["risk_level"].unique(),
        default=["low", "medium"] if set(["low", "medium"]).issubset(recs_df["risk_level"].unique()) else recs_df["risk_level"].unique()
    )
    recs_df = recs_df[recs_df["risk_level"].isin(risk_levels)]

# Minimum savings filter
if "monthly_savings" in recs_df.columns:
    min_savings = st.sidebar.slider(
        "Minimum Monthly Savings ($)",
        min_value=0,
        max_value=int(recs_df["monthly_savings"].max()),
        value=0
    )
    recs_df = recs_df[recs_df["monthly_savings"] >= min_savings]

# Minimum confidence filter
if "confidence" in recs_df.columns:
    min_confidence = st.sidebar.slider(
        "Minimum Confidence",
        min_value=0.0,
        max_value=1.0,
        value=0.5
    )
    recs_df = recs_df[recs_df["confidence"] >= min_confidence]

# Summary metrics
st.header("Recommendation Summary")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Servers with Recommendations", len(recs_df))

with col2:
    total_savings = recs_df[recs_df["monthly_savings"] > 0]["monthly_savings"].sum()
    st.metric("Total Monthly Savings", f"${total_savings:,.0f}")

with col3:
    yearly_savings = total_savings * 12
    st.metric("Total Yearly Savings", f"${yearly_savings:,.0f}")

with col4:
    low_risk = len(recs_df[recs_df["risk_level"] == "low"]) if "risk_level" in recs_df.columns else 0
    st.metric("Low Risk Changes", low_risk)

st.divider()

# Implementation phases
st.header("Implementation Phases")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Quick Wins")
    st.caption("Low risk, high confidence")

    quick_wins = recs_df[
        (recs_df["risk_level"] == "low") &
        (recs_df["confidence"] >= 0.7) &
        (recs_df["monthly_savings"] > 0)
    ] if "risk_level" in recs_df.columns else pd.DataFrame()

    if len(quick_wins) > 0:
        qw_savings = quick_wins["monthly_savings"].sum()
        st.success(f"**{len(quick_wins)}** servers")
        st.success(f"**${qw_savings:,.0f}** monthly savings")

        st.dataframe(
            quick_wins[["hostname", "instance_type", "recommended_type", "monthly_savings"]].head(10),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No quick wins identified")

with col2:
    st.markdown("### Medium Term")
    st.caption("Moderate risk or confidence")

    medium_term = recs_df[
        ((recs_df["risk_level"] == "medium") |
         ((recs_df["confidence"] >= 0.5) & (recs_df["confidence"] < 0.7))) &
        (recs_df["monthly_savings"] > 0)
    ] if "risk_level" in recs_df.columns else pd.DataFrame()

    if len(medium_term) > 0:
        mt_savings = medium_term["monthly_savings"].sum()
        st.warning(f"**{len(medium_term)}** servers")
        st.warning(f"**${mt_savings:,.0f}** monthly savings")

        st.dataframe(
            medium_term[["hostname", "instance_type", "recommended_type", "monthly_savings"]].head(10),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No medium term changes identified")

with col3:
    st.markdown("### Long Term")
    st.caption("Higher risk, requires validation")

    long_term = recs_df[
        (recs_df["risk_level"] == "high") |
        (recs_df["confidence"] < 0.5)
    ] if "risk_level" in recs_df.columns else pd.DataFrame()

    if len(long_term) > 0:
        lt_savings = long_term[long_term["monthly_savings"] > 0]["monthly_savings"].sum()
        st.error(f"**{len(long_term)}** servers")
        st.error(f"**${lt_savings:,.0f}** monthly savings")

        st.dataframe(
            long_term[["hostname", "instance_type", "recommended_type", "monthly_savings"]].head(10),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No long term changes identified")

st.divider()

# Full recommendations table
st.header("All Recommendations")

# Sort options
sort_by = st.selectbox(
    "Sort by:",
    options=["monthly_savings", "confidence", "hostname"],
    index=0
)

sort_ascending = st.checkbox("Ascending", value=False)

recs_sorted = recs_df.sort_values(sort_by, ascending=sort_ascending)

st.dataframe(
    recs_sorted[[
        "hostname", "instance_type", "recommended_type",
        "classification", "monthly_savings", "yearly_savings",
        "confidence", "risk_level", "reason"
    ]],
    use_container_width=True,
    height=400,
    column_config={
        "monthly_savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f"),
        "yearly_savings": st.column_config.NumberColumn("Yearly Savings", format="$%.2f"),
        "confidence": st.column_config.ProgressColumn("Confidence", format="%.0f%%", min_value=0, max_value=1)
    }
)

# Download button
csv = recs_sorted.to_csv(index=False)
st.download_button(
    label="Download Recommendations CSV",
    data=csv,
    file_name="rightsizing_recommendations.csv",
    mime="text/csv"
)
