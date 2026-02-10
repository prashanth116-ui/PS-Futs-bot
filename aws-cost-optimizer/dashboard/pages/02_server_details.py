"""Server details page for the dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Server Details", page_icon="🖥️", layout="wide")

st.title("Server Details")


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to view server details.")
    st.stop()

# Filters
st.sidebar.header("Filters")

# Classification filter
if "classification" in df.columns:
    selected_class = st.sidebar.multiselect(
        "Classification",
        options=df["classification"].unique(),
        default=df["classification"].unique()
    )
    df = df[df["classification"].isin(selected_class)]

# Instance type filter
if "instance_type" in df.columns:
    instance_types = st.sidebar.multiselect(
        "Instance Type",
        options=sorted(df["instance_type"].unique()),
        default=[]
    )
    if instance_types:
        df = df[df["instance_type"].isin(instance_types)]

# GSI filter
tag_columns = [c for c in df.columns if c.upper() in ["GSI", "COST_CENTER", "PROJECT"]]
if tag_columns:
    tag_col = tag_columns[0]
    gsi_values = st.sidebar.multiselect(
        "GSI",
        options=sorted(df[tag_col].dropna().unique()),
        default=[]
    )
    if gsi_values:
        df = df[df[tag_col].isin(gsi_values)]

st.markdown(f"Showing **{len(df)}** servers")

# Server table
st.header("All Servers")

# Select columns to display
display_cols = st.multiselect(
    "Columns to display:",
    options=df.columns.tolist(),
    default=["hostname", "instance_type", "vcpu", "memory_gb",
             "cpu_p95", "memory_p95", "classification", "monthly_savings"]
)

if display_cols:
    st.dataframe(
        df[display_cols],
        use_container_width=True,
        height=400,
        column_config={
            "monthly_savings": st.column_config.NumberColumn(
                "Monthly Savings",
                format="$%.2f"
            ),
            "current_monthly": st.column_config.NumberColumn(
                "Current Monthly",
                format="$%.2f"
            ),
            "cpu_p95": st.column_config.NumberColumn(
                "CPU P95 %",
                format="%.1f"
            ),
            "memory_p95": st.column_config.NumberColumn(
                "Memory P95 %",
                format="%.1f"
            ),
            "confidence": st.column_config.ProgressColumn(
                "Confidence",
                format="%.0f%%",
                min_value=0,
                max_value=1
            )
        }
    )

st.divider()

# Individual server detail
st.header("Server Deep Dive")

server_options = df["hostname"].tolist() if "hostname" in df.columns else df["server_id"].tolist()
selected_server = st.selectbox("Select a server:", server_options)

if selected_server:
    if "hostname" in df.columns:
        server_data = df[df["hostname"] == selected_server].iloc[0]
    else:
        server_data = df[df["server_id"] == selected_server].iloc[0]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Instance Info")
        st.markdown(f"**Hostname:** {server_data.get('hostname', 'N/A')}")
        st.markdown(f"**Instance ID:** {server_data.get('instance_id', 'N/A')}")
        st.markdown(f"**Instance Type:** {server_data.get('instance_type', 'N/A')}")
        st.markdown(f"**vCPU:** {server_data.get('vcpu', 'N/A')}")
        st.markdown(f"**Memory:** {server_data.get('memory_gb', 'N/A')} GB")

    with col2:
        st.markdown("### Utilization")
        if "cpu_avg" in server_data:
            st.metric("CPU Average", f"{server_data['cpu_avg']:.1f}%")
        if "cpu_p95" in server_data:
            st.metric("CPU P95", f"{server_data['cpu_p95']:.1f}%")
        if "memory_p95" in server_data:
            st.metric("Memory P95", f"{server_data['memory_p95']:.1f}%")

    with col3:
        st.markdown("### Recommendation")
        classification = server_data.get("classification", "unknown")
        if classification == "oversized":
            st.success(f"**Classification:** {classification.upper()}")
        elif classification == "undersized":
            st.error(f"**Classification:** {classification.upper()}")
        else:
            st.info(f"**Classification:** {classification.upper()}")

        if pd.notna(server_data.get("recommended_type")):
            st.markdown(f"**Recommended Type:** {server_data['recommended_type']}")
            st.markdown(f"**Monthly Savings:** ${server_data.get('monthly_savings', 0):,.2f}")
            st.markdown(f"**Confidence:** {server_data.get('confidence', 0)*100:.0f}%")
            st.markdown(f"**Risk Level:** {server_data.get('risk_level', 'N/A')}")
