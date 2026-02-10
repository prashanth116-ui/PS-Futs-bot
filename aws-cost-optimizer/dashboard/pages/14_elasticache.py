"""ElastiCache Analysis page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

st.set_page_config(page_title="ElastiCache Analysis", page_icon="🗃️", layout="wide")

st.markdown("""
    <h1 style="color: #3B48CC;">🗃️ ElastiCache Analysis</h1>
    <p style="color: #666;">Optimize cache clusters, identify idle caches, and reduce in-memory data costs</p>
""", unsafe_allow_html=True)

# ElastiCache Node Pricing (approximate hourly rates, us-east-1)
ELASTICACHE_PRICING = {
    "cache.t3.micro": {"vcpu": 2, "memory_gb": 0.5, "hourly": 0.017},
    "cache.t3.small": {"vcpu": 2, "memory_gb": 1.37, "hourly": 0.034},
    "cache.t3.medium": {"vcpu": 2, "memory_gb": 3.09, "hourly": 0.068},
    "cache.m5.large": {"vcpu": 2, "memory_gb": 6.38, "hourly": 0.124},
    "cache.m5.xlarge": {"vcpu": 4, "memory_gb": 12.93, "hourly": 0.248},
    "cache.m5.2xlarge": {"vcpu": 8, "memory_gb": 26.04, "hourly": 0.496},
    "cache.r5.large": {"vcpu": 2, "memory_gb": 13.07, "hourly": 0.166},
    "cache.r5.xlarge": {"vcpu": 4, "memory_gb": 26.32, "hourly": 0.332},
    "cache.r5.2xlarge": {"vcpu": 8, "memory_gb": 52.82, "hourly": 0.664},
    "cache.r6g.large": {"vcpu": 2, "memory_gb": 13.07, "hourly": 0.133},
    "cache.r6g.xlarge": {"vcpu": 4, "memory_gb": 26.32, "hourly": 0.266},
}

# Graviton equivalents
GRAVITON_MAPPING = {
    "cache.m5.large": "cache.m6g.large",
    "cache.m5.xlarge": "cache.m6g.xlarge",
    "cache.r5.large": "cache.r6g.large",
    "cache.r5.xlarge": "cache.r6g.xlarge",
    "cache.r5.2xlarge": "cache.r6g.2xlarge",
}


def generate_sample_elasticache_data():
    """Generate sample ElastiCache data for demonstration."""
    clusters = [
        {"name": "prod-redis-primary", "engine": "Redis", "node_type": "cache.r5.xlarge", "nodes": 3, "env": "Production"},
        {"name": "prod-redis-sessions", "engine": "Redis", "node_type": "cache.r5.large", "nodes": 2, "env": "Production"},
        {"name": "prod-memcached", "engine": "Memcached", "node_type": "cache.m5.xlarge", "nodes": 3, "env": "Production"},
        {"name": "stage-redis", "engine": "Redis", "node_type": "cache.t3.medium", "nodes": 1, "env": "Staging"},
        {"name": "dev-redis", "engine": "Redis", "node_type": "cache.t3.small", "nodes": 1, "env": "Development"},
        {"name": "analytics-cache", "engine": "Redis", "node_type": "cache.r5.2xlarge", "nodes": 2, "env": "Production"},
        {"name": "legacy-cache", "engine": "Memcached", "node_type": "cache.m5.large", "nodes": 2, "env": "Production"},
    ]

    data = []
    for cluster in clusters:
        specs = ELASTICACHE_PRICING.get(cluster["node_type"], {"vcpu": 2, "memory_gb": 8, "hourly": 0.2})
        monthly_cost = specs["hourly"] * 730 * cluster["nodes"]

        # Random utilization based on environment
        if cluster["env"] == "Development":
            cpu_avg = np.random.uniform(5, 20)
            memory_used_pct = np.random.uniform(10, 40)
            connections = np.random.randint(5, 50)
        elif cluster["env"] == "Staging":
            cpu_avg = np.random.uniform(10, 35)
            memory_used_pct = np.random.uniform(20, 50)
            connections = np.random.randint(20, 200)
        else:
            cpu_avg = np.random.uniform(15, 60)
            memory_used_pct = np.random.uniform(30, 85)
            connections = np.random.randint(100, 2000)

        data.append({
            "cluster_name": cluster["name"],
            "engine": cluster["engine"],
            "node_type": cluster["node_type"],
            "nodes": cluster["nodes"],
            "vcpu": specs["vcpu"],
            "memory_gb": specs["memory_gb"],
            "environment": cluster["env"],
            "cpu_avg": cpu_avg,
            "memory_used_pct": memory_used_pct,
            "connections": connections,
            "hit_rate_pct": np.random.uniform(85, 99.5),
            "monthly_cost": monthly_cost,
        })

    return pd.DataFrame(data)


# Load or generate data
if "elasticache_data" not in st.session_state:
    st.session_state["elasticache_data"] = generate_sample_elasticache_data()

df = st.session_state["elasticache_data"]

# Summary metrics
st.markdown("### 📊 Overview")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Clusters", len(df))

with col2:
    st.metric("Monthly Spend", f"${df['monthly_cost'].sum():,.0f}")

with col3:
    total_nodes = df["nodes"].sum()
    st.metric("Total Nodes", total_nodes)

with col4:
    redis_count = len(df[df["engine"] == "Redis"])
    st.metric("Redis Clusters", redis_count)

with col5:
    avg_hit_rate = df["hit_rate_pct"].mean()
    st.metric("Avg Hit Rate", f"{avg_hit_rate:.1f}%")

st.markdown("---")

# Analysis tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Cluster Inventory",
    "💡 Optimization Recommendations",
    "📈 Cost Analysis",
    "🚀 Graviton Migration"
])

with tab1:
    st.markdown("### Cluster Inventory")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        engine_filter = st.multiselect("Engine", df["engine"].unique(), default=list(df["engine"].unique()))
    with col2:
        env_filter = st.multiselect("Environment", df["environment"].unique(), default=list(df["environment"].unique()))
    with col3:
        min_cost = st.slider("Min Monthly Cost ($)", 0, int(df["monthly_cost"].max()), 0)

    filtered = df[
        (df["engine"].isin(engine_filter)) &
        (df["environment"].isin(env_filter)) &
        (df["monthly_cost"] >= min_cost)
    ]

    st.dataframe(
        filtered,
        column_config={
            "cpu_avg": st.column_config.NumberColumn("CPU Avg %", format="%.1f"),
            "memory_used_pct": st.column_config.NumberColumn("Memory Used %", format="%.1f"),
            "hit_rate_pct": st.column_config.NumberColumn("Hit Rate %", format="%.1f"),
            "monthly_cost": st.column_config.NumberColumn("Monthly Cost", format="$%.2f"),
        },
        use_container_width=True,
        height=400
    )

with tab2:
    st.markdown("### Optimization Recommendations")

    recommendations = []

    for _, row in df.iterrows():
        # Check for low utilization
        if row["memory_used_pct"] < 30 and row["cpu_avg"] < 20:
            recommendations.append({
                "cluster": row["cluster_name"],
                "issue": "Low Utilization",
                "recommendation": f"Consider downsizing from {row['node_type']}",
                "savings": row["monthly_cost"] * 0.4,
                "risk": "Low"
            })

        # Check for over-provisioned nodes
        if row["nodes"] > 2 and row["memory_used_pct"] < 40:
            recommendations.append({
                "cluster": row["cluster_name"],
                "issue": "Too Many Nodes",
                "recommendation": f"Reduce node count from {row['nodes']}",
                "savings": row["monthly_cost"] / row["nodes"],
                "risk": "Medium"
            })

        # Check for low hit rate
        if row["hit_rate_pct"] < 90:
            recommendations.append({
                "cluster": row["cluster_name"],
                "issue": "Low Cache Hit Rate",
                "recommendation": f"Hit rate {row['hit_rate_pct']:.1f}% - review caching strategy",
                "savings": 0,
                "risk": "Low"
            })

        # Check for non-production oversizing
        if row["environment"] in ["Development", "Staging"] and "r5" in row["node_type"]:
            recommendations.append({
                "cluster": row["cluster_name"],
                "issue": "Oversized for Non-Prod",
                "recommendation": "Use t3 instances for dev/staging",
                "savings": row["monthly_cost"] * 0.6,
                "risk": "Low"
            })

    if recommendations:
        recs_df = pd.DataFrame(recommendations)
        total_savings = recs_df["savings"].sum()

        col1, col2 = st.columns([1, 3])
        with col1:
            st.metric("Potential Savings", f"${total_savings:,.0f}/mo")

        st.dataframe(
            recs_df,
            column_config={
                "savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f"),
            },
            use_container_width=True
        )
    else:
        st.success("All clusters appear optimized!")

with tab3:
    st.markdown("### Cost Analysis")

    col1, col2 = st.columns(2)

    with col1:
        by_engine = df.groupby("engine")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.pie(values=by_engine.values, names=by_engine.index, title="Cost by Engine")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        by_env = df.groupby("environment")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.bar(x=by_env.index, y=by_env.values, title="Cost by Environment")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    # Memory usage heatmap
    st.markdown("#### Cluster Performance Overview")
    fig = go.Figure(data=[
        go.Bar(name='CPU %', x=df["cluster_name"], y=df["cpu_avg"], marker_color='#FF9900'),
        go.Bar(name='Memory %', x=df["cluster_name"], y=df["memory_used_pct"], marker_color='#232F3E')
    ])
    fig.update_layout(barmode='group', height=400, xaxis_tickangle=45)
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.markdown("### Graviton Migration Opportunities")

    graviton_candidates = []
    for _, row in df.iterrows():
        if row["node_type"] in GRAVITON_MAPPING:
            current_cost = row["monthly_cost"]
            graviton_type = GRAVITON_MAPPING[row["node_type"]]
            savings = current_cost * 0.20  # ~20% savings

            graviton_candidates.append({
                "cluster": row["cluster_name"],
                "current_type": row["node_type"],
                "graviton_type": graviton_type,
                "nodes": row["nodes"],
                "current_cost": current_cost,
                "estimated_savings": savings,
                "engine": row["engine"]
            })

    if graviton_candidates:
        grav_df = pd.DataFrame(graviton_candidates)
        total_graviton_savings = grav_df["estimated_savings"].sum()

        st.success(f"💰 Potential Graviton Savings: **${total_graviton_savings:,.0f}/month**")

        st.dataframe(
            grav_df,
            column_config={
                "current_cost": st.column_config.NumberColumn("Current Cost", format="$%.2f"),
                "estimated_savings": st.column_config.NumberColumn("Est. Savings", format="$%.2f"),
            },
            use_container_width=True
        )

        st.info("""
        **Graviton Benefits for ElastiCache:**
        - Up to 20% cost savings
        - Up to 45% better price-performance
        - Supported by both Redis and Memcached
        - Same APIs and data formats
        - Easy migration via modify cluster
        """)
    else:
        st.info("No Graviton migration candidates found - clusters may already be on Graviton.")
