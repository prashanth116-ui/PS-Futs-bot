"""Cost analysis page for the dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Cost Analysis", page_icon="💰", layout="wide")

st.title("Cost Analysis")


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to view cost analysis.")
    st.stop()

if "current_monthly" not in df.columns:
    st.warning("Cost data not available in this report.")
    st.stop()

# Summary metrics
st.header("Cost Overview")

total_current = df["current_monthly"].sum()
total_savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum() if "monthly_savings" in df.columns else 0
total_optimized = total_current - total_savings

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Current Monthly", f"${total_current:,.0f}")

with col2:
    st.metric("After Optimization", f"${total_optimized:,.0f}")

with col3:
    st.metric("Monthly Savings", f"${total_savings:,.0f}",
              delta=f"-{(total_savings/total_current*100):.1f}%" if total_current > 0 else None,
              delta_color="inverse")

with col4:
    st.metric("Yearly Savings", f"${total_savings * 12:,.0f}")

st.divider()

# Current vs Optimized comparison
st.header("Spend Comparison")

col1, col2 = st.columns(2)

with col1:
    # Bar chart
    fig = go.Figure(data=[
        go.Bar(name='Current', x=['Monthly Spend'], y=[total_current], marker_color='#6c757d'),
        go.Bar(name='Optimized', x=['Monthly Spend'], y=[total_optimized], marker_color='#28a745')
    ])
    fig.update_layout(
        title="Current vs. Optimized Monthly Spend",
        barmode='group',
        height=350
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    # Savings waterfall
    fig = go.Figure(go.Waterfall(
        name="Savings",
        orientation="v",
        measure=["absolute", "relative", "total"],
        x=["Current Spend", "Savings", "Optimized Spend"],
        text=[f"${total_current:,.0f}", f"-${total_savings:,.0f}", f"${total_optimized:,.0f}"],
        y=[total_current, -total_savings, total_optimized],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        decreasing={"marker": {"color": "#28a745"}},
        increasing={"marker": {"color": "#dc3545"}},
        totals={"marker": {"color": "#1f77b4"}}
    ))
    fig.update_layout(
        title="Savings Waterfall",
        height=350
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# Cost breakdown by instance type
st.header("Cost Breakdown")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### By Instance Type")

    by_type = df.groupby("instance_type")["current_monthly"].sum().sort_values(ascending=False).head(10)

    fig = px.pie(
        values=by_type.values,
        names=by_type.index,
        title="Top 10 Instance Types by Spend"
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.markdown("### By Classification")

    if "classification" in df.columns:
        by_class = df.groupby("classification").agg({
            "current_monthly": "sum",
            "monthly_savings": lambda x: x[x > 0].sum() if "monthly_savings" in df.columns else 0
        }).reset_index()

        fig = px.bar(
            by_class,
            x="classification",
            y="current_monthly",
            color="classification",
            color_discrete_map={
                "oversized": "#28a745",
                "right_sized": "#6c757d",
                "undersized": "#dc3545",
                "unknown": "#ffc107"
            },
            title="Spend by Classification"
        )
        fig.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# Savings by GSI
st.header("Savings by GSI/Cost Center")

tag_columns = [c for c in df.columns if c.upper() in ["GSI", "COST_CENTER", "PROJECT"]]

if tag_columns and "monthly_savings" in df.columns:
    tag_col = tag_columns[0]

    by_tag = df.groupby(tag_col).agg({
        "current_monthly": "sum",
        "monthly_savings": lambda x: x[x > 0].sum()
    }).sort_values("monthly_savings", ascending=True).tail(15).reset_index()

    fig = px.bar(
        by_tag,
        y=tag_col,
        x="monthly_savings",
        orientation="h",
        title=f"Monthly Savings by {tag_col}",
        color="monthly_savings",
        color_continuous_scale="Greens"
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No GSI/Cost Center tag data available for breakdown.")

st.divider()

# 12-month projection
st.header("12-Month Savings Projection")

months = list(range(1, 13))
month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
cumulative = [total_savings * m for m in months]

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=month_names,
    y=cumulative,
    mode='lines+markers',
    name='Cumulative Savings',
    line=dict(color='#28a745', width=3),
    fill='tozeroy',
    fillcolor='rgba(40, 167, 69, 0.2)'
))

fig.add_trace(go.Scatter(
    x=month_names,
    y=[total_savings] * 12,
    mode='lines',
    name='Monthly Savings',
    line=dict(color='#1f77b4', dash='dash')
))

fig.update_layout(
    title="Projected Savings Over 12 Months",
    xaxis_title="Month",
    yaxis_title="Savings ($)",
    height=400
)

st.plotly_chart(fig, use_container_width=True)

# Summary table
st.subheader("Monthly Projection Details")

projection_data = []
running_total = 0

for i, month in enumerate(month_names):
    running_total += total_savings
    projection_data.append({
        "Month": month,
        "Monthly Savings": f"${total_savings:,.0f}",
        "Cumulative Savings": f"${running_total:,.0f}"
    })

st.dataframe(
    pd.DataFrame(projection_data),
    use_container_width=True,
    hide_index=True
)
