"""Settings page - Dark mode, saved filters, notifications."""

import streamlit as st
import json
from pathlib import Path
from datetime import datetime

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")

st.title("Settings")
st.caption("Configure dashboard preferences, saved filters, and notifications")

# Initialize session state for settings
if "settings" not in st.session_state:
    st.session_state["settings"] = {
        "theme": "light",
        "default_view": "Server Analysis",
        "auto_refresh": False,
        "refresh_interval": 5,
        "saved_filters": [],
        "notifications": {
            "slack_webhook": "",
            "email": "",
            "threshold_savings": 1000,
        },
        "export_preferences": {
            "include_charts": True,
            "include_raw_data": True,
            "format": "xlsx",
        }
    }

settings = st.session_state["settings"]

# Appearance
st.header("Appearance")

col1, col2 = st.columns(2)

with col1:
    theme = st.selectbox(
        "Theme",
        options=["Light", "Dark", "Auto (System)"],
        index=["Light", "Dark", "Auto (System)"].index(settings["theme"].title()) if settings["theme"].title() in ["Light", "Dark", "Auto (System)"] else 0
    )
    settings["theme"] = theme.lower().replace(" (system)", "")

    if theme == "Dark":
        st.markdown("""
        <style>
        .stApp {
            background-color: #1e1e1e;
            color: #ffffff;
        }
        .stMarkdown {
            color: #ffffff;
        }
        </style>
        """, unsafe_allow_html=True)
        st.info("Dark mode applies custom styling. Full dark mode support depends on Streamlit theme settings.")

with col2:
    default_view = st.selectbox(
        "Default View",
        options=["Server Analysis", "Recommendations", "Cost Breakdown", "Contention"],
        index=["Server Analysis", "Recommendations", "Cost Breakdown", "Contention"].index(settings["default_view"]) if settings["default_view"] in ["Server Analysis", "Recommendations", "Cost Breakdown", "Contention"] else 0
    )
    settings["default_view"] = default_view

st.divider()

# Saved Filters
st.header("Saved Filters")

st.markdown("Save frequently used filter combinations for quick access.")

# Current filters display
if settings["saved_filters"]:
    st.subheader("Your Saved Filters")

    for i, filter_config in enumerate(settings["saved_filters"]):
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            st.markdown(f"**{filter_config['name']}**")
            st.caption(f"Classification: {filter_config.get('classification', 'All')}, "
                      f"Risk: {filter_config.get('risk_level', 'All')}, "
                      f"Min Savings: ${filter_config.get('min_savings', 0)}")
        with col2:
            st.caption(f"Created: {filter_config.get('created', 'Unknown')}")
        with col3:
            if st.button("Delete", key=f"delete_filter_{i}"):
                settings["saved_filters"].pop(i)
                st.rerun()

    st.divider()

# Create new filter
st.subheader("Create New Saved Filter")

with st.form("new_filter_form"):
    filter_name = st.text_input("Filter Name", placeholder="e.g., Production Oversized")

    col1, col2, col3 = st.columns(3)

    with col1:
        filter_classification = st.multiselect(
            "Classification",
            options=["oversized", "right_sized", "undersized"],
            default=[]
        )

    with col2:
        filter_risk = st.multiselect(
            "Risk Level",
            options=["low", "medium", "high"],
            default=[]
        )

    with col3:
        filter_min_savings = st.number_input(
            "Minimum Savings ($)",
            min_value=0,
            value=0
        )

    filter_gsi = st.text_input("GSI (comma-separated)", placeholder="WebPlatform, Database")
    filter_environment = st.multiselect(
        "Environment",
        options=["Production", "Staging", "Development", "Test"],
        default=[]
    )

    submitted = st.form_submit_button("Save Filter")

    if submitted and filter_name:
        new_filter = {
            "name": filter_name,
            "classification": filter_classification if filter_classification else "All",
            "risk_level": filter_risk if filter_risk else "All",
            "min_savings": filter_min_savings,
            "gsi": filter_gsi,
            "environment": filter_environment if filter_environment else "All",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        settings["saved_filters"].append(new_filter)
        st.success(f"Filter '{filter_name}' saved!")
        st.rerun()

st.divider()

# Notifications
st.header("Notifications")

st.markdown("Configure alerts for significant savings opportunities.")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Slack Integration")

    slack_webhook = st.text_input(
        "Slack Webhook URL",
        value=settings["notifications"]["slack_webhook"],
        type="password",
        placeholder="https://hooks.slack.com/services/..."
    )
    settings["notifications"]["slack_webhook"] = slack_webhook

    if slack_webhook:
        if st.button("Test Slack Connection"):
            try:
                import requests
                response = requests.post(
                    slack_webhook,
                    json={"text": "AWS Cost Optimizer: Test notification successful!"},
                    timeout=5
                )
                if response.status_code == 200:
                    st.success("Test message sent!")
                else:
                    st.error(f"Failed: {response.text}")
            except Exception as e:
                st.error(f"Error: {e}")

with col2:
    st.subheader("Alert Thresholds")

    threshold_savings = st.number_input(
        "Alert when monthly savings exceed ($)",
        min_value=0,
        value=settings["notifications"]["threshold_savings"],
        step=100
    )
    settings["notifications"]["threshold_savings"] = threshold_savings

    email = st.text_input(
        "Email for alerts (optional)",
        value=settings["notifications"]["email"],
        placeholder="admin@example.com"
    )
    settings["notifications"]["email"] = email

st.divider()

# Export Preferences
st.header("Export Preferences")

col1, col2 = st.columns(2)

with col1:
    include_charts = st.checkbox(
        "Include charts in exports",
        value=settings["export_preferences"]["include_charts"]
    )
    settings["export_preferences"]["include_charts"] = include_charts

    include_raw = st.checkbox(
        "Include raw data sheets",
        value=settings["export_preferences"]["include_raw_data"]
    )
    settings["export_preferences"]["include_raw_data"] = include_raw

with col2:
    export_format = st.selectbox(
        "Default export format",
        options=["xlsx", "csv", "pdf"],
        index=["xlsx", "csv", "pdf"].index(settings["export_preferences"]["format"])
    )
    settings["export_preferences"]["format"] = export_format

st.divider()

# Classification Thresholds (moved from main app for centralized settings)
st.header("Classification Thresholds")

st.markdown("Adjust the CPU and Memory thresholds used for server classification.")

col1, col2 = st.columns(2)

with col1:
    st.subheader("CPU Thresholds (%)")

    if "thresholds" not in st.session_state:
        st.session_state["thresholds"] = {
            "cpu_oversized": 40,
            "cpu_undersized": 70,
            "mem_oversized": 50,
            "mem_undersized": 75,
        }

    cpu_oversized = st.slider(
        "Oversized if P95 below:",
        min_value=10, max_value=60,
        value=st.session_state["thresholds"]["cpu_oversized"]
    )

    cpu_undersized = st.slider(
        "Undersized if P95 above:",
        min_value=50, max_value=95,
        value=st.session_state["thresholds"]["cpu_undersized"]
    )

with col2:
    st.subheader("Memory Thresholds (%)")

    mem_oversized = st.slider(
        "Oversized if P95 below:",
        min_value=10, max_value=70,
        value=st.session_state["thresholds"]["mem_oversized"]
    )

    mem_undersized = st.slider(
        "Undersized if P95 above:",
        min_value=50, max_value=95,
        value=st.session_state["thresholds"]["mem_undersized"]
    )

if st.button("Save Threshold Settings"):
    st.session_state["thresholds"] = {
        "cpu_oversized": cpu_oversized,
        "cpu_undersized": cpu_undersized,
        "mem_oversized": mem_oversized,
        "mem_undersized": mem_undersized,
    }
    st.success("Thresholds saved!")

st.divider()

# Data Management
st.header("Data Management")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Clear Session Data")

    if st.button("Clear Uploaded Report"):
        if "report_file" in st.session_state:
            del st.session_state["report_file"]
            st.success("Report cleared!")
            st.rerun()
        else:
            st.info("No report loaded.")

    if st.button("Clear Implementation Status"):
        if "implementation_status" in st.session_state:
            st.session_state["implementation_status"] = {}
            st.success("Implementation status cleared!")
        else:
            st.info("No status data to clear.")

with col2:
    st.subheader("Export Settings")

    settings_json = json.dumps(settings, indent=2)
    st.download_button(
        label="Export Settings (JSON)",
        data=settings_json,
        file_name="cost_optimizer_settings.json",
        mime="application/json"
    )

    st.subheader("Import Settings")

    uploaded_settings = st.file_uploader(
        "Upload settings file",
        type=["json"]
    )

    if uploaded_settings:
        try:
            imported = json.load(uploaded_settings)
            st.session_state["settings"] = imported
            st.success("Settings imported!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to import: {e}")

st.divider()

# About
st.header("About")

st.markdown("""
**AWS Cost Optimizer Dashboard** v1.1

Features:
- Server classification and rightsizing recommendations
- Custom classification thresholds
- Implementation tracking
- What-If scenario analysis
- Graviton migration recommendations
- Terraform/CLI code generation
- Savings Plans comparison
- Drill-down analysis by GSI/Environment
- PDF report export

Built with Streamlit, Plotly, and Python.
""")
