"""Summary page for the dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Summary", page_icon="📊", layout="wide")

st.title("Executive Summary")


def load_data():
    """Load data from session state or uploaded file."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to view the summary.")
    st.stop()

# Key metrics
st.header("Key Metrics")

col1, col2, col3, col4 = st.columns(4)

total_servers = len(df)
total_spend = df["current_monthly"].sum() if "current_monthly" in df.columns else 0
total_savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum() if "monthly_savings" in df.columns else 0
oversized = len(df[df["classification"] == "oversized"]) if "classification" in df.columns else 0

with col1:
    st.metric("Total Servers", total_servers)

with col2:
    st.metric("Monthly Spend", f"${total_spend:,.0f}")

with col3:
    st.metric("Potential Savings", f"${total_savings:,.0f}/month")

with col4:
    st.metric("Oversized Servers", oversized)

st.divider()

# Classification breakdown
st.header("Server Classification")

col1, col2 = st.columns([1, 2])

with col1:
    if "classification" in df.columns:
        class_counts = df["classification"].value_counts()

        fig = go.Figure(data=[go.Pie(
            labels=class_counts.index,
            values=class_counts.values,
            hole=0.4,
            marker_colors=["#28a745", "#6c757d", "#dc3545", "#ffc107"]
        )])
        fig.update_layout(height=300, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)

with col2:
    if "classification" in df.columns:
        st.markdown("""
        | Classification | Description |
        |----------------|-------------|
        | **Oversized** | Resources significantly underutilized. Safe to downsize. |
        | **Right-sized** | Resources appropriately matched to workload. |
        | **Undersized** | Resources constrained. Consider upgrading. |
        | **Unknown** | Insufficient data for classification. |
        """)

        st.markdown("### Action Summary")
        st.success(f"✅ **{oversized}** servers can be downsized for immediate savings")

        undersized = len(df[df["classification"] == "undersized"])
        if undersized > 0:
            st.warning(f"⚠️ **{undersized}** servers may need upgrades")

# Savings by tag
st.header("Savings by GSI/Cost Center")

if "monthly_savings" in df.columns:
    # Check for GSI or similar tag column
    tag_columns = [c for c in df.columns if c.upper() in ["GSI", "COST_CENTER", "PROJECT"]]

    if tag_columns:
        tag_col = tag_columns[0]
        by_tag = df.groupby(tag_col).agg({
            "current_monthly": "sum",
            "monthly_savings": "sum"
        }).sort_values("monthly_savings", ascending=False)

        fig = px.bar(
            by_tag.reset_index(),
            x=tag_col,
            y="monthly_savings",
            color="monthly_savings",
            color_continuous_scale="Greens"
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No GSI or cost center tags found in the data.")
