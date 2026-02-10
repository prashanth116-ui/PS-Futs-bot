"""Graviton Migration Recommendations page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Graviton Recommendations", page_icon="🚀", layout="wide")

st.title("Graviton Migration Recommendations")
st.caption("Identify instances that can migrate to ARM-based Graviton for additional savings")

# Graviton equivalents mapping
GRAVITON_EQUIVALENTS = {
    # M5 -> M6g/M7g
    "m5.large": {"graviton": "m6g.large", "savings_pct": 20},
    "m5.xlarge": {"graviton": "m6g.xlarge", "savings_pct": 20},
    "m5.2xlarge": {"graviton": "m6g.2xlarge", "savings_pct": 20},
    "m5.4xlarge": {"graviton": "m6g.4xlarge", "savings_pct": 20},
    # C5 -> C6g/C7g
    "c5.large": {"graviton": "c6g.large", "savings_pct": 20},
    "c5.xlarge": {"graviton": "c6g.xlarge", "savings_pct": 20},
    "c5.2xlarge": {"graviton": "c6g.2xlarge", "savings_pct": 20},
    "c5.4xlarge": {"graviton": "c6g.4xlarge", "savings_pct": 20},
    # R5 -> R6g/R7g
    "r5.large": {"graviton": "r6g.large", "savings_pct": 20},
    "r5.xlarge": {"graviton": "r6g.xlarge", "savings_pct": 20},
    "r5.2xlarge": {"graviton": "r6g.2xlarge", "savings_pct": 20},
    "r5.4xlarge": {"graviton": "r6g.4xlarge", "savings_pct": 20},
    # T3 -> T4g
    "t3.micro": {"graviton": "t4g.micro", "savings_pct": 20},
    "t3.small": {"graviton": "t4g.small", "savings_pct": 20},
    "t3.medium": {"graviton": "t4g.medium", "savings_pct": 20},
    "t3.large": {"graviton": "t4g.large", "savings_pct": 20},
    "t3.xlarge": {"graviton": "t4g.xlarge", "savings_pct": 20},
}

# Workload compatibility (mock assessment)
COMPATIBLE_WORKLOADS = [
    "Web servers",
    "Application servers",
    "Microservices",
    "Containerized apps",
    "Open-source databases",
    "In-memory caches",
    "Gaming servers",
    "Media encoding",
]

INCOMPATIBLE_WORKLOADS = [
    "Windows applications",
    "x86-specific software",
    "Legacy 32-bit apps",
    "Some commercial databases",
]


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to view Graviton recommendations.")
    st.stop()

# Analyze Graviton eligibility
st.header("Graviton Eligibility Analysis")


def analyze_graviton_eligibility(row):
    """Determine if an instance can migrate to Graviton."""
    instance_type = row.get("instance_type", "")

    if instance_type in GRAVITON_EQUIVALENTS:
        equiv = GRAVITON_EQUIVALENTS[instance_type]
        current_cost = row.get("current_monthly", 0)
        graviton_savings = current_cost * (equiv["savings_pct"] / 100)
        return {
            "eligible": True,
            "graviton_type": equiv["graviton"],
            "savings_pct": equiv["savings_pct"],
            "monthly_savings": graviton_savings,
            "yearly_savings": graviton_savings * 12,
        }

    return {
        "eligible": False,
        "graviton_type": None,
        "savings_pct": 0,
        "monthly_savings": 0,
        "yearly_savings": 0,
    }


# Add Graviton analysis to dataframe
graviton_analysis = df.apply(analyze_graviton_eligibility, axis=1, result_type="expand")
df_graviton = pd.concat([df, graviton_analysis], axis=1)

eligible_df = df_graviton[df_graviton["eligible"] == True]
ineligible_df = df_graviton[df_graviton["eligible"] == False]

# Summary metrics
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Graviton Eligible", len(eligible_df))

with col2:
    st.metric("Not Eligible", len(ineligible_df))

with col3:
    total_graviton_savings = eligible_df["monthly_savings"].sum()
    st.metric("Additional Monthly Savings", f"${total_graviton_savings:,.0f}")

with col4:
    st.metric("Additional Yearly Savings", f"${total_graviton_savings * 12:,.0f}")

st.divider()

# Eligible instances
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Graviton Migration Candidates")

    if len(eligible_df) > 0:
        display_df = eligible_df[[
            "hostname", "instance_type", "graviton_type",
            "current_monthly", "monthly_savings", "savings_pct"
        ]].copy()

        display_df = display_df.sort_values("monthly_savings", ascending=False)

        st.dataframe(
            display_df,
            use_container_width=True,
            height=400,
            column_config={
                "hostname": "Server",
                "instance_type": "Current Type",
                "graviton_type": "Graviton Type",
                "current_monthly": st.column_config.NumberColumn("Current Cost", format="$%.2f"),
                "monthly_savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f"),
                "savings_pct": st.column_config.NumberColumn("Savings %", format="%d%%"),
            }
        )
    else:
        st.info("No instances eligible for Graviton migration in current data.")

with col2:
    st.subheader("Savings by Instance Family")

    if len(eligible_df) > 0:
        # Extract family from instance type
        eligible_df["family"] = eligible_df["instance_type"].str.split(".").str[0]

        by_family = eligible_df.groupby("family").agg({
            "monthly_savings": "sum",
            "hostname": "count"
        }).rename(columns={"hostname": "count"})

        fig = px.pie(
            values=by_family["monthly_savings"],
            names=by_family.index,
            title="Savings by Instance Family"
        )
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# Compatibility checklist
st.header("Migration Compatibility Checklist")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### Compatible Workloads")
    for workload in COMPATIBLE_WORKLOADS:
        st.markdown(f"✅ {workload}")

with col2:
    st.markdown("### Requires Validation")
    for workload in INCOMPATIBLE_WORKLOADS:
        st.markdown(f"⚠️ {workload}")

st.divider()

# Migration plan
st.header("Migration Plan Generator")

if len(eligible_df) > 0:
    st.markdown("### Select servers to include in migration plan")

    selected_for_migration = st.multiselect(
        "Select servers:",
        options=eligible_df["hostname"].tolist() if "hostname" in eligible_df.columns else [],
        default=eligible_df["hostname"].tolist()[:5] if "hostname" in eligible_df.columns else []
    )

    if selected_for_migration:
        migration_df = eligible_df[eligible_df["hostname"].isin(selected_for_migration)]

        st.markdown("### Migration Summary")

        total_migration_savings = migration_df["monthly_savings"].sum()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Servers to Migrate", len(migration_df))
        with col2:
            st.metric("Monthly Savings", f"${total_migration_savings:,.2f}")
        with col3:
            st.metric("Yearly Savings", f"${total_migration_savings * 12:,.2f}")

        # Export migration plan
        st.markdown("### Export Migration Plan")

        migration_plan = migration_df[[
            "hostname", "instance_type", "graviton_type", "monthly_savings"
        ]].copy()
        migration_plan["migration_status"] = "Planned"
        migration_plan["target_date"] = ""
        migration_plan["notes"] = ""

        csv = migration_plan.to_csv(index=False)
        st.download_button(
            label="Download Migration Plan (CSV)",
            data=csv,
            file_name="graviton_migration_plan.csv",
            mime="text/csv"
        )

st.divider()

# Additional resources
st.header("Resources")

st.markdown("""
**AWS Graviton Documentation:**
- [AWS Graviton Processor](https://aws.amazon.com/ec2/graviton/)
- [Graviton Getting Started Guide](https://github.com/aws/aws-graviton-getting-started)
- [Graviton Technical Guide](https://docs.aws.amazon.com/whitepapers/latest/aws-graviton-performance-testing/aws-graviton-performance-testing.html)

**Key Benefits:**
- Up to 40% better price-performance vs x86
- Built by AWS using 64-bit Arm Neoverse cores
- Supported by most Linux distributions
- Compatible with containers and Kubernetes
""")
