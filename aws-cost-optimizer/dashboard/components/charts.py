"""Reusable chart components for the dashboard."""

import plotly.express as px
import plotly.graph_objects as go
from typing import Any, Dict, List, Optional
import pandas as pd


def create_classification_pie(
    df: pd.DataFrame,
    classification_col: str = "classification"
) -> go.Figure:
    """Create a pie chart showing server classification breakdown.

    Args:
        df: DataFrame with classification data
        classification_col: Column name for classification

    Returns:
        Plotly figure
    """
    if classification_col not in df.columns:
        return go.Figure()

    class_counts = df[classification_col].value_counts()

    fig = go.Figure(data=[go.Pie(
        labels=class_counts.index,
        values=class_counts.values,
        hole=0.4,
        marker_colors=["#28a745", "#6c757d", "#dc3545", "#ffc107"],
        textinfo='label+percent'
    )])

    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        margin=dict(t=20, b=20, l=20, r=20)
    )

    return fig


def create_utilization_scatter(
    df: pd.DataFrame,
    x_col: str = "cpu_p95",
    y_col: str = "memory_p95",
    color_col: str = "classification",
    hover_cols: Optional[List[str]] = None
) -> go.Figure:
    """Create a scatter plot of resource utilization.

    Args:
        df: DataFrame with utilization data
        x_col: Column for x-axis
        y_col: Column for y-axis
        color_col: Column for color encoding
        hover_cols: Additional columns for hover data

    Returns:
        Plotly figure
    """
    if x_col not in df.columns or y_col not in df.columns:
        return go.Figure()

    hover_cols = hover_cols or ["hostname", "instance_type"]

    fig = px.scatter(
        df,
        x=x_col,
        y=y_col,
        color=color_col if color_col in df.columns else None,
        hover_data=[c for c in hover_cols if c in df.columns],
        color_discrete_map={
            "oversized": "#28a745",
            "right_sized": "#6c757d",
            "undersized": "#dc3545",
            "unknown": "#ffc107"
        }
    )

    # Add threshold lines
    fig.add_hline(y=75, line_dash="dash", line_color="orange",
                  annotation_text="Memory Threshold")
    fig.add_vline(x=70, line_dash="dash", line_color="orange",
                  annotation_text="CPU Threshold")

    fig.update_layout(
        xaxis_title="CPU P95 (%)",
        yaxis_title="Memory P95 (%)",
        xaxis=dict(range=[0, 100]),
        yaxis=dict(range=[0, 100])
    )

    return fig


def create_savings_bar(
    df: pd.DataFrame,
    name_col: str = "hostname",
    savings_col: str = "monthly_savings",
    color_col: str = "classification",
    top_n: int = 20
) -> go.Figure:
    """Create a bar chart of savings by server.

    Args:
        df: DataFrame with savings data
        name_col: Column for server names
        savings_col: Column for savings values
        color_col: Column for color encoding
        top_n: Number of top servers to show

    Returns:
        Plotly figure
    """
    if savings_col not in df.columns:
        return go.Figure()

    # Filter to positive savings and sort
    savings_df = df[df[savings_col] > 0].nlargest(top_n, savings_col)

    if len(savings_df) == 0:
        return go.Figure()

    fig = px.bar(
        savings_df,
        x=name_col if name_col in savings_df.columns else savings_df.index,
        y=savings_col,
        color=color_col if color_col in savings_df.columns else None,
        color_discrete_map={
            "oversized": "#28a745",
            "undersized": "#dc3545"
        }
    )

    fig.update_layout(
        xaxis_tickangle=45,
        xaxis_title="Server",
        yaxis_title="Monthly Savings ($)"
    )

    return fig


def create_cost_comparison(
    current: float,
    optimized: float
) -> go.Figure:
    """Create a cost comparison bar chart.

    Args:
        current: Current monthly cost
        optimized: Optimized monthly cost

    Returns:
        Plotly figure
    """
    fig = go.Figure(data=[
        go.Bar(
            name='Current',
            x=['Monthly Spend'],
            y=[current],
            marker_color='#6c757d'
        ),
        go.Bar(
            name='Optimized',
            x=['Monthly Spend'],
            y=[optimized],
            marker_color='#28a745'
        )
    ])

    fig.update_layout(
        barmode='group',
        yaxis_title="Cost ($)",
        showlegend=True
    )

    return fig


def create_savings_timeline(
    monthly_savings: float,
    months: int = 12
) -> go.Figure:
    """Create a savings timeline projection.

    Args:
        monthly_savings: Monthly savings amount
        months: Number of months to project

    Returns:
        Plotly figure
    """
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][:months]
    cumulative = [monthly_savings * (i + 1) for i in range(months)]

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

    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Cumulative Savings ($)"
    )

    return fig


def create_cost_by_tag(
    df: pd.DataFrame,
    tag_col: str,
    cost_col: str = "current_monthly",
    savings_col: str = "monthly_savings"
) -> go.Figure:
    """Create a bar chart of costs/savings by tag.

    Args:
        df: DataFrame with cost data
        tag_col: Column for tag grouping
        cost_col: Column for cost values
        savings_col: Column for savings values

    Returns:
        Plotly figure
    """
    if tag_col not in df.columns:
        return go.Figure()

    by_tag = df.groupby(tag_col).agg({
        cost_col: "sum",
        savings_col: lambda x: x[x > 0].sum() if savings_col in df.columns else 0
    }).sort_values(savings_col, ascending=True).reset_index()

    fig = go.Figure(data=[
        go.Bar(
            name='Current Cost',
            y=by_tag[tag_col],
            x=by_tag[cost_col],
            orientation='h',
            marker_color='#6c757d'
        ),
        go.Bar(
            name='Savings',
            y=by_tag[tag_col],
            x=by_tag[savings_col],
            orientation='h',
            marker_color='#28a745'
        )
    ])

    fig.update_layout(
        barmode='group',
        xaxis_title="Amount ($)",
        yaxis_title=tag_col
    )

    return fig
