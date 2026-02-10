"""Lambda Functions Analysis page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

st.set_page_config(page_title="Lambda Analysis", page_icon="⚡", layout="wide")

st.markdown("""
    <h1 style="color: #3B48CC;">⚡ Lambda Functions Analysis</h1>
    <p style="color: #666;">Optimize function memory, identify unused functions, and reduce compute costs</p>
""", unsafe_allow_html=True)

# Lambda Pricing (us-east-1)
LAMBDA_PRICING = {
    "request_price": 0.0000002,  # $0.20 per 1M requests
    "duration_price_per_gb_second": 0.0000166667,  # $0.0000166667 per GB-second
    "arm_discount": 0.20,  # 20% cheaper for ARM
}


def generate_sample_lambda_data():
    """Generate sample Lambda function data for demonstration."""
    functions = [
        {"name": "api-handler", "runtime": "nodejs18.x", "memory_mb": 1024, "arch": "x86_64", "env": "Production"},
        {"name": "image-processor", "runtime": "python3.11", "memory_mb": 3008, "arch": "x86_64", "env": "Production"},
        {"name": "data-transformer", "runtime": "python3.11", "memory_mb": 2048, "arch": "x86_64", "env": "Production"},
        {"name": "notification-sender", "runtime": "nodejs18.x", "memory_mb": 256, "arch": "arm64", "env": "Production"},
        {"name": "cron-cleanup", "runtime": "python3.9", "memory_mb": 512, "arch": "x86_64", "env": "Production"},
        {"name": "auth-validator", "runtime": "nodejs18.x", "memory_mb": 512, "arch": "x86_64", "env": "Production"},
        {"name": "report-generator", "runtime": "python3.11", "memory_mb": 4096, "arch": "x86_64", "env": "Production"},
        {"name": "webhook-receiver", "runtime": "go1.x", "memory_mb": 128, "arch": "arm64", "env": "Production"},
        {"name": "stage-api-handler", "runtime": "nodejs18.x", "memory_mb": 1024, "arch": "x86_64", "env": "Staging"},
        {"name": "dev-test-function", "runtime": "python3.11", "memory_mb": 256, "arch": "x86_64", "env": "Development"},
        {"name": "old-legacy-handler", "runtime": "nodejs14.x", "memory_mb": 512, "arch": "x86_64", "env": "Production"},
        {"name": "unused-experiment", "runtime": "python3.9", "memory_mb": 1024, "arch": "x86_64", "env": "Development"},
    ]

    data = []
    for func in functions:
        # Simulate usage patterns
        if "unused" in func["name"] or "legacy" in func["name"]:
            invocations_day = np.random.randint(0, 10)
            avg_duration_ms = np.random.uniform(50, 500)
        elif func["env"] == "Production":
            invocations_day = np.random.randint(1000, 100000)
            avg_duration_ms = np.random.uniform(50, 2000)
        else:
            invocations_day = np.random.randint(10, 1000)
            avg_duration_ms = np.random.uniform(100, 1000)

        # Calculate costs
        monthly_invocations = invocations_day * 30
        gb_seconds = (func["memory_mb"] / 1024) * (avg_duration_ms / 1000) * monthly_invocations

        request_cost = monthly_invocations * LAMBDA_PRICING["request_price"]
        duration_cost = gb_seconds * LAMBDA_PRICING["duration_price_per_gb_second"]

        if func["arch"] == "arm64":
            duration_cost = duration_cost * (1 - LAMBDA_PRICING["arm_discount"])

        monthly_cost = request_cost + duration_cost

        # Memory utilization (simulated)
        memory_used_pct = np.random.uniform(20, 95) if invocations_day > 100 else np.random.uniform(10, 50)

        data.append({
            "function_name": func["name"],
            "runtime": func["runtime"],
            "memory_mb": func["memory_mb"],
            "architecture": func["arch"],
            "environment": func["env"],
            "invocations_day": invocations_day,
            "avg_duration_ms": avg_duration_ms,
            "memory_used_pct": memory_used_pct,
            "monthly_cost": monthly_cost,
            "last_invoked_days": np.random.randint(0, 90),
        })

    return pd.DataFrame(data)


# Load or generate data
if "lambda_data" not in st.session_state:
    st.session_state["lambda_data"] = generate_sample_lambda_data()

df = st.session_state["lambda_data"]

# Summary metrics
st.markdown("### 📊 Overview")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Functions", len(df))

with col2:
    st.metric("Monthly Spend", f"${df['monthly_cost'].sum():,.2f}")

with col3:
    arm_count = len(df[df["architecture"] == "arm64"])
    st.metric("ARM Functions", arm_count)

with col4:
    total_invocations = df["invocations_day"].sum() * 30
    st.metric("Monthly Invocations", f"{total_invocations/1e6:.1f}M")

with col5:
    unused = len(df[df["invocations_day"] < 10])
    st.metric("Low-Use Functions", unused)

st.markdown("---")

# Analysis tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Function Inventory",
    "💡 Optimization Recommendations",
    "📈 Cost Analysis",
    "🚀 ARM Migration"
])

with tab1:
    st.markdown("### Function Inventory")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        runtime_filter = st.multiselect("Runtime", df["runtime"].unique(), default=list(df["runtime"].unique()))
    with col2:
        env_filter = st.multiselect("Environment", df["environment"].unique(), default=list(df["environment"].unique()))
    with col3:
        arch_filter = st.multiselect("Architecture", df["architecture"].unique(), default=list(df["architecture"].unique()))

    filtered = df[
        (df["runtime"].isin(runtime_filter)) &
        (df["environment"].isin(env_filter)) &
        (df["architecture"].isin(arch_filter))
    ]

    st.dataframe(
        filtered,
        column_config={
            "invocations_day": st.column_config.NumberColumn("Daily Invocations", format="%d"),
            "avg_duration_ms": st.column_config.NumberColumn("Avg Duration (ms)", format="%.1f"),
            "memory_used_pct": st.column_config.NumberColumn("Memory Used %", format="%.1f"),
            "monthly_cost": st.column_config.NumberColumn("Monthly Cost", format="$%.4f"),
        },
        use_container_width=True,
        height=400
    )

with tab2:
    st.markdown("### Optimization Recommendations")

    recommendations = []

    for _, row in df.iterrows():
        # Check for unused functions
        if row["invocations_day"] < 10 and row["last_invoked_days"] > 30:
            recommendations.append({
                "function": row["function_name"],
                "issue": "Unused/Rarely Used",
                "recommendation": "Consider deleting or archiving this function",
                "savings": row["monthly_cost"],
                "risk": "Medium"
            })

        # Check for over-provisioned memory
        if row["memory_used_pct"] < 40 and row["invocations_day"] > 100:
            optimal_memory = int(row["memory_mb"] * (row["memory_used_pct"] / 100) * 1.5)
            optimal_memory = max(128, min(optimal_memory, row["memory_mb"]))

            current_cost = row["monthly_cost"]
            savings_pct = (row["memory_mb"] - optimal_memory) / row["memory_mb"]
            savings = current_cost * savings_pct * 0.5  # Conservative estimate

            if savings > 0.01:
                recommendations.append({
                    "function": row["function_name"],
                    "issue": "Over-Provisioned Memory",
                    "recommendation": f"Reduce from {row['memory_mb']}MB to ~{optimal_memory}MB",
                    "savings": savings,
                    "risk": "Low"
                })

        # Check for deprecated runtimes
        deprecated = ["nodejs14.x", "python3.7", "python3.8"]
        if row["runtime"] in deprecated:
            recommendations.append({
                "function": row["function_name"],
                "issue": "Deprecated Runtime",
                "recommendation": f"Upgrade {row['runtime']} to latest version",
                "savings": 0,
                "risk": "Medium"
            })

    if recommendations:
        recs_df = pd.DataFrame(recommendations)
        total_savings = recs_df["savings"].sum()

        col1, col2 = st.columns([1, 3])
        with col1:
            st.metric("Potential Savings", f"${total_savings:,.2f}/mo")

        st.dataframe(
            recs_df,
            column_config={
                "savings": st.column_config.NumberColumn("Monthly Savings", format="$%.4f"),
            },
            use_container_width=True
        )
    else:
        st.success("All functions appear optimized!")

with tab3:
    st.markdown("### Cost Analysis")

    col1, col2 = st.columns(2)

    with col1:
        by_runtime = df.groupby("runtime")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.pie(values=by_runtime.values, names=by_runtime.index, title="Cost by Runtime")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        by_env = df.groupby("environment")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.bar(x=by_env.index, y=by_env.values, title="Cost by Environment")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    # Invocations vs Cost
    st.markdown("#### Invocations vs Cost")
    fig = px.scatter(
        df,
        x="invocations_day",
        y="monthly_cost",
        color="runtime",
        size="memory_mb",
        hover_name="function_name",
        title="Daily Invocations vs Monthly Cost (bubble size = memory)"
    )
    fig.update_layout(height=400)
    fig.update_xaxes(type="log")
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.markdown("### ARM (Graviton2) Migration Opportunities")

    arm_candidates = df[df["architecture"] == "x86_64"].copy()

    if len(arm_candidates) > 0:
        # Calculate potential savings
        arm_candidates["arm_savings"] = arm_candidates["monthly_cost"] * LAMBDA_PRICING["arm_discount"]
        total_arm_savings = arm_candidates["arm_savings"].sum()

        st.success(f"💰 Potential ARM Migration Savings: **${total_arm_savings:,.2f}/month**")

        # Compatible runtimes for ARM
        arm_compatible = ["nodejs18.x", "python3.11", "python3.9", "go1.x"]

        compatible = arm_candidates[arm_candidates["runtime"].isin(arm_compatible)]
        incompatible = arm_candidates[~arm_candidates["runtime"].isin(arm_compatible)]

        st.markdown("#### Compatible Functions (Ready to Migrate)")
        if len(compatible) > 0:
            st.dataframe(
                compatible[["function_name", "runtime", "memory_mb", "monthly_cost", "arm_savings"]],
                column_config={
                    "monthly_cost": st.column_config.NumberColumn("Current Cost", format="$%.4f"),
                    "arm_savings": st.column_config.NumberColumn("Est. Savings", format="$%.4f"),
                },
                use_container_width=True
            )
        else:
            st.info("No compatible functions found.")

        if len(incompatible) > 0:
            st.markdown("#### Requires Runtime Upgrade First")
            st.dataframe(
                incompatible[["function_name", "runtime", "memory_mb", "monthly_cost"]],
                column_config={
                    "monthly_cost": st.column_config.NumberColumn("Current Cost", format="$%.4f"),
                },
                use_container_width=True
            )

        st.info("""
        **ARM/Graviton2 Benefits for Lambda:**
        - Up to 20% cost savings
        - Up to 34% better price-performance
        - Supported by Node.js, Python, Go, Java, Ruby, .NET
        - Same function code, just change architecture setting
        """)
    else:
        st.success("All functions are already on ARM architecture!")
