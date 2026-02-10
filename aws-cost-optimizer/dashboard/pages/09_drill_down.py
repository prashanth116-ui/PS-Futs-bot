"""Drill-Down Analysis page - explore by GSI, Environment, Team."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Drill-Down Analysis", page_icon="🔍", layout="wide")

st.title("Drill-Down Analysis")
st.caption("Explore cost optimization opportunities by GSI, Environment, Team, and more")


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to use drill-down analysis.")
    st.stop()

# Determine available grouping columns
grouping_options = []
potential_groups = ["GSI", "Environment", "Team", "classification", "instance_type", "risk_level"]

for col in potential_groups:
    if col in df.columns and df[col].notna().any():
        grouping_options.append(col)

if not grouping_options:
    st.warning("No grouping columns available in the data.")
    st.stop()

# Sidebar for drill-down selection
st.sidebar.header("Drill-Down Selection")

primary_group = st.sidebar.selectbox(
    "Primary Grouping",
    options=grouping_options,
    index=0
)

# Get available values for primary group
primary_values = df[primary_group].dropna().unique().tolist()

selected_primary = st.sidebar.selectbox(
    f"Select {primary_group}",
    options=["All"] + primary_values
)

# Secondary grouping (optional)
secondary_options = [g for g in grouping_options if g != primary_group]
if secondary_options:
    secondary_group = st.sidebar.selectbox(
        "Secondary Grouping (optional)",
        options=["None"] + secondary_options
    )
else:
    secondary_group = "None"

# Filter data
if selected_primary != "All":
    filtered_df = df[df[primary_group] == selected_primary]
else:
    filtered_df = df.copy()

# Main content
st.header(f"Analysis by {primary_group}")

if selected_primary != "All":
    st.subheader(f"Showing: {selected_primary}")

# Summary metrics for selection
col1, col2, col3, col4 = st.columns(4)

total_servers = len(filtered_df)
total_spend = filtered_df["current_monthly"].sum() if "current_monthly" in filtered_df.columns else 0
total_savings = filtered_df[filtered_df["monthly_savings"] > 0]["monthly_savings"].sum() if "monthly_savings" in filtered_df.columns else 0
oversized = len(filtered_df[filtered_df["classification"] == "oversized"]) if "classification" in filtered_df.columns else 0

with col1:
    st.metric("Servers", total_servers)
with col2:
    st.metric("Monthly Spend", f"${total_spend:,.0f}")
with col3:
    st.metric("Potential Savings", f"${total_savings:,.0f}")
with col4:
    st.metric("Oversized", oversized)

st.divider()

# Breakdown charts
col1, col2 = st.columns(2)

with col1:
    st.subheader(f"Cost by {primary_group}")

    if selected_primary == "All":
        # Show all groups
        by_group = df.groupby(primary_group).agg({
            "current_monthly": "sum",
            "monthly_savings": lambda x: x[x > 0].sum() if "monthly_savings" in df.columns else 0
        }).reset_index()

        fig = px.bar(
            by_group,
            x=primary_group,
            y="current_monthly",
            color="monthly_savings",
            color_continuous_scale="Greens",
            labels={"current_monthly": "Monthly Cost ($)", "monthly_savings": "Savings Potential"}
        )
        fig.update_layout(height=400, xaxis_tickangle=45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        # Show secondary breakdown
        if secondary_group != "None":
            by_secondary = filtered_df.groupby(secondary_group).agg({
                "current_monthly": "sum"
            }).reset_index()

            fig = px.pie(
                by_secondary,
                values="current_monthly",
                names=secondary_group,
                title=f"Cost Distribution by {secondary_group}"
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            # Show by classification
            if "classification" in filtered_df.columns:
                by_class = filtered_df["classification"].value_counts()
                fig = px.pie(
                    values=by_class.values,
                    names=by_class.index,
                    title="Server Classification",
                    color=by_class.index,
                    color_discrete_map={
                        "oversized": "#28a745",
                        "right_sized": "#6c757d",
                        "undersized": "#dc3545",
                    }
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Savings Opportunity")

    if "monthly_savings" in filtered_df.columns:
        savings_df = filtered_df[filtered_df["monthly_savings"] > 0].nlargest(10, "monthly_savings")

        if len(savings_df) > 0:
            fig = px.bar(
                savings_df,
                x="hostname" if "hostname" in savings_df.columns else savings_df.index,
                y="monthly_savings",
                color="classification" if "classification" in savings_df.columns else None,
                color_discrete_map={
                    "oversized": "#28a745",
                    "undersized": "#dc3545",
                },
                title="Top 10 Savings Opportunities"
            )
            fig.update_layout(height=400, xaxis_tickangle=45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No savings opportunities in this selection.")
    else:
        st.info("Savings data not available.")

st.divider()

# Detailed server list
st.subheader("Server Details")

# Column selection
available_cols = filtered_df.columns.tolist()
default_cols = ["hostname", "instance_type", "classification", "cpu_p95", "memory_p95", "current_monthly", "monthly_savings"]
display_cols = [c for c in default_cols if c in available_cols]

selected_cols = st.multiselect(
    "Select columns to display:",
    options=available_cols,
    default=display_cols
)

if selected_cols:
    st.dataframe(
        filtered_df[selected_cols].sort_values("monthly_savings" if "monthly_savings" in selected_cols else selected_cols[0], ascending=False),
        use_container_width=True,
        height=400,
        column_config={
            "current_monthly": st.column_config.NumberColumn("Monthly Cost", format="$%.2f"),
            "monthly_savings": st.column_config.NumberColumn("Savings", format="$%.2f"),
            "cpu_p95": st.column_config.NumberColumn("CPU P95 %", format="%.1f"),
            "memory_p95": st.column_config.NumberColumn("Mem P95 %", format="%.1f"),
        }
    )

st.divider()

# Comparison view (if showing all)
if selected_primary == "All" and len(primary_values) > 1:
    st.header(f"Compare {primary_group}s")

    compare_values = st.multiselect(
        f"Select {primary_group}s to compare:",
        options=primary_values,
        default=primary_values[:min(5, len(primary_values))]
    )

    if len(compare_values) >= 2:
        compare_df = df[df[primary_group].isin(compare_values)]

        comparison_data = compare_df.groupby(primary_group).agg({
            "hostname": "count",
            "current_monthly": "sum",
            "monthly_savings": lambda x: x[x > 0].sum() if "monthly_savings" in df.columns else 0,
            "cpu_p95": "mean",
            "memory_p95": "mean",
        }).rename(columns={"hostname": "server_count"})

        comparison_data["savings_pct"] = (comparison_data["monthly_savings"] / comparison_data["current_monthly"] * 100).fillna(0)

        col1, col2 = st.columns(2)

        with col1:
            fig = px.bar(
                comparison_data.reset_index(),
                x=primary_group,
                y=["current_monthly", "monthly_savings"],
                barmode="group",
                title="Cost vs Savings Comparison"
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.scatter(
                comparison_data.reset_index(),
                x="cpu_p95",
                y="memory_p95",
                size="server_count",
                color=primary_group,
                title="Average Utilization Comparison",
                labels={"cpu_p95": "Avg CPU P95 %", "memory_p95": "Avg Memory P95 %"}
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            comparison_data.round(2),
            use_container_width=True,
            column_config={
                "current_monthly": st.column_config.NumberColumn("Monthly Cost", format="$%.0f"),
                "monthly_savings": st.column_config.NumberColumn("Savings", format="$%.0f"),
                "savings_pct": st.column_config.NumberColumn("Savings %", format="%.1f%%"),
                "cpu_p95": st.column_config.NumberColumn("Avg CPU %", format="%.1f"),
                "memory_p95": st.column_config.NumberColumn("Avg Mem %", format="%.1f"),
            }
        )

# Export filtered data
st.divider()
csv = filtered_df.to_csv(index=False)
st.download_button(
    label="Download Filtered Data (CSV)",
    data=csv,
    file_name=f"drill_down_{primary_group}_{selected_primary}.csv".replace(" ", "_"),
    mime="text/csv"
)
