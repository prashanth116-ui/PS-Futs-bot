"""Reusable filter components for the dashboard."""

import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple


def apply_classification_filter(
    df: pd.DataFrame,
    default_all: bool = True
) -> pd.DataFrame:
    """Add classification filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        default_all: Whether to select all classifications by default

    Returns:
        Filtered DataFrame
    """
    if "classification" not in df.columns:
        return df

    options = df["classification"].unique().tolist()

    selected = st.sidebar.multiselect(
        "Classification",
        options=options,
        default=options if default_all else []
    )

    if selected:
        return df[df["classification"].isin(selected)]
    return df


def apply_instance_type_filter(
    df: pd.DataFrame,
    default_all: bool = True
) -> pd.DataFrame:
    """Add instance type filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        default_all: Whether to select all types by default

    Returns:
        Filtered DataFrame
    """
    if "instance_type" not in df.columns:
        return df

    options = sorted(df["instance_type"].unique().tolist())

    selected = st.sidebar.multiselect(
        "Instance Type",
        options=options,
        default=[] if default_all else []  # Empty by default since there are many types
    )

    if selected:
        return df[df["instance_type"].isin(selected)]
    return df


def apply_tag_filter(
    df: pd.DataFrame,
    tag_name: str,
    label: Optional[str] = None
) -> pd.DataFrame:
    """Add a tag-based filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        tag_name: Column name for the tag (e.g., "GSI", "Environment")
        label: Display label for the filter

    Returns:
        Filtered DataFrame
    """
    if tag_name not in df.columns:
        return df

    options = sorted(df[tag_name].dropna().unique().tolist())

    selected = st.sidebar.multiselect(
        label or tag_name,
        options=options,
        default=[]
    )

    if selected:
        return df[df[tag_name].isin(selected)]
    return df


def apply_savings_filter(
    df: pd.DataFrame,
    column: str = "monthly_savings"
) -> pd.DataFrame:
    """Add minimum savings filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        column: Column name for savings

    Returns:
        Filtered DataFrame
    """
    if column not in df.columns:
        return df

    max_val = int(df[column].max()) if df[column].max() > 0 else 1000

    min_savings = st.sidebar.slider(
        "Minimum Monthly Savings ($)",
        min_value=0,
        max_value=max_val,
        value=0
    )

    if min_savings > 0:
        return df[df[column] >= min_savings]
    return df


def apply_confidence_filter(
    df: pd.DataFrame,
    column: str = "confidence"
) -> pd.DataFrame:
    """Add minimum confidence filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        column: Column name for confidence

    Returns:
        Filtered DataFrame
    """
    if column not in df.columns:
        return df

    min_confidence = st.sidebar.slider(
        "Minimum Confidence",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.1
    )

    if min_confidence > 0:
        return df[df[column] >= min_confidence]
    return df


def apply_risk_filter(
    df: pd.DataFrame,
    column: str = "risk_level"
) -> pd.DataFrame:
    """Add risk level filter to sidebar and return filtered DataFrame.

    Args:
        df: DataFrame to filter
        column: Column name for risk level

    Returns:
        Filtered DataFrame
    """
    if column not in df.columns:
        return df

    options = df[column].unique().tolist()
    default_selected = [r for r in ["low", "medium"] if r in options]

    selected = st.sidebar.multiselect(
        "Risk Level",
        options=options,
        default=default_selected
    )

    if selected:
        return df[df[column].isin(selected)]
    return df


def apply_all_filters(
    df: pd.DataFrame,
    include_classification: bool = True,
    include_instance_type: bool = True,
    include_gsi: bool = True,
    include_savings: bool = False,
    include_confidence: bool = False,
    include_risk: bool = False
) -> pd.DataFrame:
    """Apply multiple filters from sidebar.

    Args:
        df: DataFrame to filter
        include_*: Whether to include each filter type

    Returns:
        Filtered DataFrame
    """
    st.sidebar.header("Filters")

    filtered_df = df.copy()

    if include_classification:
        filtered_df = apply_classification_filter(filtered_df)

    if include_instance_type:
        filtered_df = apply_instance_type_filter(filtered_df)

    if include_gsi:
        # Look for common tag columns
        for tag in ["GSI", "gsi", "COST_CENTER", "cost_center", "Project", "project"]:
            if tag in df.columns:
                filtered_df = apply_tag_filter(filtered_df, tag)
                break

    if include_savings:
        filtered_df = apply_savings_filter(filtered_df)

    if include_confidence:
        filtered_df = apply_confidence_filter(filtered_df)

    if include_risk:
        filtered_df = apply_risk_filter(filtered_df)

    return filtered_df


def get_sort_options(
    df: pd.DataFrame
) -> Tuple[str, bool]:
    """Add sort options to sidebar.

    Args:
        df: DataFrame for column options

    Returns:
        Tuple of (sort_column, ascending)
    """
    sortable_cols = []

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    string_cols = df.select_dtypes(include=['object']).columns.tolist()

    sortable_cols = numeric_cols + string_cols

    default_col = "monthly_savings" if "monthly_savings" in sortable_cols else sortable_cols[0] if sortable_cols else None

    sort_by = st.sidebar.selectbox(
        "Sort by",
        options=sortable_cols,
        index=sortable_cols.index(default_col) if default_col in sortable_cols else 0
    )

    ascending = st.sidebar.checkbox("Ascending", value=False)

    return sort_by, ascending
