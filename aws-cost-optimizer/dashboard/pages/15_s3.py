"""S3 Buckets Analysis page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

st.set_page_config(page_title="S3 Analysis", page_icon="🪣", layout="wide")

st.markdown("""
    <h1 style="color: #3B48CC;">🪣 S3 Storage Analysis</h1>
    <p style="color: #666;">Optimize storage classes, identify unused buckets, and implement lifecycle policies</p>
""", unsafe_allow_html=True)

# S3 Storage Class Pricing (per GB-month, us-east-1)
S3_PRICING = {
    "STANDARD": {"storage": 0.023, "retrieval": 0.0, "min_days": 0},
    "INTELLIGENT_TIERING": {"storage": 0.023, "retrieval": 0.0, "min_days": 0},
    "STANDARD_IA": {"storage": 0.0125, "retrieval": 0.01, "min_days": 30},
    "ONEZONE_IA": {"storage": 0.01, "retrieval": 0.01, "min_days": 30},
    "GLACIER_IR": {"storage": 0.004, "retrieval": 0.03, "min_days": 90},
    "GLACIER_FLEXIBLE": {"storage": 0.0036, "retrieval": 0.03, "min_days": 90},
    "GLACIER_DEEP": {"storage": 0.00099, "retrieval": 0.02, "min_days": 180},
}


def generate_sample_s3_data():
    """Generate sample S3 bucket data for demonstration."""
    buckets = [
        {"name": "prod-app-assets", "class": "STANDARD", "size_gb": 500, "env": "Production", "purpose": "Application"},
        {"name": "prod-user-uploads", "class": "STANDARD", "size_gb": 2000, "env": "Production", "purpose": "User Data"},
        {"name": "prod-logs", "class": "STANDARD", "size_gb": 5000, "env": "Production", "purpose": "Logs"},
        {"name": "data-lake-raw", "class": "STANDARD", "size_gb": 50000, "env": "Production", "purpose": "Analytics"},
        {"name": "data-lake-processed", "class": "STANDARD_IA", "size_gb": 20000, "env": "Production", "purpose": "Analytics"},
        {"name": "backups-weekly", "class": "GLACIER_FLEXIBLE", "size_gb": 100000, "env": "Production", "purpose": "Backups"},
        {"name": "backups-monthly", "class": "GLACIER_DEEP", "size_gb": 500000, "env": "Production", "purpose": "Backups"},
        {"name": "staging-assets", "class": "STANDARD", "size_gb": 100, "env": "Staging", "purpose": "Application"},
        {"name": "dev-test-data", "class": "STANDARD", "size_gb": 50, "env": "Development", "purpose": "Test Data"},
        {"name": "old-migration-data", "class": "STANDARD", "size_gb": 10000, "env": "Unknown", "purpose": "Migration"},
        {"name": "temp-analytics", "class": "STANDARD", "size_gb": 1000, "env": "Development", "purpose": "Analytics"},
        {"name": "compliance-archive", "class": "GLACIER_DEEP", "size_gb": 200000, "env": "Production", "purpose": "Compliance"},
    ]

    data = []
    for bucket in buckets:
        pricing = S3_PRICING.get(bucket["class"], S3_PRICING["STANDARD"])
        monthly_cost = bucket["size_gb"] * pricing["storage"]

        # Simulate access patterns
        if bucket["class"] in ["GLACIER_FLEXIBLE", "GLACIER_DEEP"]:
            access_frequency = "Rare"
            last_accessed_days = np.random.randint(30, 365)
        elif bucket["class"] in ["STANDARD_IA", "ONEZONE_IA"]:
            access_frequency = "Infrequent"
            last_accessed_days = np.random.randint(7, 60)
        else:
            if "logs" in bucket["name"] or "old" in bucket["name"]:
                access_frequency = "Infrequent"
                last_accessed_days = np.random.randint(14, 90)
            else:
                access_frequency = "Frequent"
                last_accessed_days = np.random.randint(0, 7)

        # Objects count estimate
        objects_count = int(bucket["size_gb"] * np.random.uniform(100, 10000))

        data.append({
            "bucket_name": bucket["name"],
            "storage_class": bucket["class"],
            "size_gb": bucket["size_gb"],
            "size_tb": bucket["size_gb"] / 1024,
            "objects_count": objects_count,
            "environment": bucket["env"],
            "purpose": bucket["purpose"],
            "access_frequency": access_frequency,
            "last_accessed_days": last_accessed_days,
            "has_lifecycle_policy": np.random.choice([True, False], p=[0.3, 0.7]),
            "monthly_cost": monthly_cost,
        })

    return pd.DataFrame(data)


# Load or generate data
if "s3_data" not in st.session_state:
    st.session_state["s3_data"] = generate_sample_s3_data()

df = st.session_state["s3_data"]

# Summary metrics
st.markdown("### 📊 Overview")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Buckets", len(df))

with col2:
    st.metric("Monthly Spend", f"${df['monthly_cost'].sum():,.0f}")

with col3:
    total_storage_tb = df["size_tb"].sum()
    st.metric("Total Storage", f"{total_storage_tb:,.1f} TB")

with col4:
    standard_pct = len(df[df["storage_class"] == "STANDARD"]) / len(df) * 100
    st.metric("In Standard Class", f"{standard_pct:.0f}%")

with col5:
    no_lifecycle = len(df[df["has_lifecycle_policy"] == False])
    st.metric("No Lifecycle Policy", no_lifecycle)

st.markdown("---")

# Analysis tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Bucket Inventory",
    "💡 Storage Class Optimization",
    "📈 Cost Analysis",
    "🔄 Lifecycle Recommendations"
])

with tab1:
    st.markdown("### Bucket Inventory")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        class_filter = st.multiselect("Storage Class", df["storage_class"].unique(), default=list(df["storage_class"].unique()))
    with col2:
        env_filter = st.multiselect("Environment", df["environment"].unique(), default=list(df["environment"].unique()))
    with col3:
        purpose_filter = st.multiselect("Purpose", df["purpose"].unique(), default=list(df["purpose"].unique()))

    filtered = df[
        (df["storage_class"].isin(class_filter)) &
        (df["environment"].isin(env_filter)) &
        (df["purpose"].isin(purpose_filter))
    ]

    st.dataframe(
        filtered[["bucket_name", "storage_class", "size_tb", "objects_count", "environment",
                  "access_frequency", "has_lifecycle_policy", "monthly_cost"]],
        column_config={
            "size_tb": st.column_config.NumberColumn("Size (TB)", format="%.2f"),
            "objects_count": st.column_config.NumberColumn("Objects", format="%d"),
            "monthly_cost": st.column_config.NumberColumn("Monthly Cost", format="$%.2f"),
            "has_lifecycle_policy": st.column_config.CheckboxColumn("Lifecycle Policy"),
        },
        use_container_width=True,
        height=400
    )

with tab2:
    st.markdown("### Storage Class Optimization")

    recommendations = []

    for _, row in df.iterrows():
        # Check STANDARD buckets with infrequent access
        if row["storage_class"] == "STANDARD":
            if row["access_frequency"] == "Infrequent" or row["last_accessed_days"] > 30:
                current_cost = row["monthly_cost"]
                ia_cost = row["size_gb"] * S3_PRICING["STANDARD_IA"]["storage"]
                savings = current_cost - ia_cost

                recommendations.append({
                    "bucket": row["bucket_name"],
                    "current_class": row["storage_class"],
                    "recommended_class": "STANDARD_IA",
                    "reason": f"Infrequent access ({row['last_accessed_days']} days since last access)",
                    "monthly_savings": savings,
                    "risk": "Low"
                })

            elif row["access_frequency"] == "Rare" or row["last_accessed_days"] > 90:
                current_cost = row["monthly_cost"]
                glacier_cost = row["size_gb"] * S3_PRICING["GLACIER_IR"]["storage"]
                savings = current_cost - glacier_cost

                recommendations.append({
                    "bucket": row["bucket_name"],
                    "current_class": row["storage_class"],
                    "recommended_class": "GLACIER_IR",
                    "reason": f"Rare access ({row['last_accessed_days']} days since last access)",
                    "monthly_savings": savings,
                    "risk": "Medium"
                })

        # Check for Intelligent Tiering candidates
        if row["storage_class"] == "STANDARD" and row["size_gb"] > 1000:
            recommendations.append({
                "bucket": row["bucket_name"],
                "current_class": row["storage_class"],
                "recommended_class": "INTELLIGENT_TIERING",
                "reason": "Large bucket - automatic optimization",
                "monthly_savings": row["monthly_cost"] * 0.15,  # Estimate
                "risk": "Low"
            })

    if recommendations:
        recs_df = pd.DataFrame(recommendations)
        total_savings = recs_df["monthly_savings"].sum()

        col1, col2 = st.columns([1, 3])
        with col1:
            st.metric("Potential Savings", f"${total_savings:,.0f}/mo")

        st.dataframe(
            recs_df,
            column_config={
                "monthly_savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f"),
            },
            use_container_width=True
        )

        st.info("""
        **S3 Storage Classes (from most to least expensive):**
        1. **STANDARD** - Frequently accessed data
        2. **INTELLIGENT_TIERING** - Automatic optimization for unknown patterns
        3. **STANDARD_IA** - Infrequent access (30-day minimum)
        4. **ONEZONE_IA** - Infrequent access, single AZ (lower durability)
        5. **GLACIER_IR** - Archive with instant retrieval
        6. **GLACIER_FLEXIBLE** - Archive (minutes to hours retrieval)
        7. **GLACIER_DEEP** - Long-term archive (12+ hours retrieval)
        """)
    else:
        st.success("All buckets appear to be using optimal storage classes!")

with tab3:
    st.markdown("### Cost Analysis")

    col1, col2 = st.columns(2)

    with col1:
        by_class = df.groupby("storage_class")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.pie(values=by_class.values, names=by_class.index, title="Cost by Storage Class")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        by_purpose = df.groupby("purpose")["monthly_cost"].sum().sort_values(ascending=False)
        fig = px.bar(x=by_purpose.index, y=by_purpose.values, title="Cost by Purpose")
        fig.update_layout(height=350)
        st.plotly_chart(fig, use_container_width=True)

    # Size distribution
    st.markdown("#### Storage Distribution by Class")
    by_class_size = df.groupby("storage_class")["size_tb"].sum().sort_values(ascending=False)
    fig = px.bar(
        x=by_class_size.index,
        y=by_class_size.values,
        title="Storage Size by Class (TB)",
        color=by_class_size.index
    )
    fig.update_layout(height=400, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    # Top buckets by cost
    st.markdown("#### Top 10 Buckets by Cost")
    top_buckets = df.nlargest(10, "monthly_cost")[["bucket_name", "storage_class", "size_tb", "monthly_cost"]]
    fig = px.bar(
        top_buckets,
        x="bucket_name",
        y="monthly_cost",
        color="storage_class",
        title="Top 10 Buckets by Monthly Cost"
    )
    fig.update_layout(height=400, xaxis_tickangle=45)
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.markdown("### Lifecycle Policy Recommendations")

    no_lifecycle = df[df["has_lifecycle_policy"] == False].copy()

    if len(no_lifecycle) > 0:
        st.warning(f"**{len(no_lifecycle)} buckets** have no lifecycle policy configured.")

        # Estimate potential savings
        lifecycle_recommendations = []

        for _, row in no_lifecycle.iterrows():
            if row["purpose"] == "Logs":
                lifecycle_recommendations.append({
                    "bucket": row["bucket_name"],
                    "recommendation": "Transition to IA after 30 days, Glacier after 90 days, delete after 365 days",
                    "estimated_savings": row["monthly_cost"] * 0.6,
                })
            elif row["purpose"] == "Backups":
                lifecycle_recommendations.append({
                    "bucket": row["bucket_name"],
                    "recommendation": "Transition to Glacier after 7 days, Deep Archive after 90 days",
                    "estimated_savings": row["monthly_cost"] * 0.7,
                })
            elif row["purpose"] == "Analytics":
                lifecycle_recommendations.append({
                    "bucket": row["bucket_name"],
                    "recommendation": "Use Intelligent Tiering or transition older partitions to IA",
                    "estimated_savings": row["monthly_cost"] * 0.3,
                })
            else:
                lifecycle_recommendations.append({
                    "bucket": row["bucket_name"],
                    "recommendation": "Review access patterns and implement appropriate lifecycle rules",
                    "estimated_savings": row["monthly_cost"] * 0.2,
                })

        lifecycle_df = pd.DataFrame(lifecycle_recommendations)
        total_lifecycle_savings = lifecycle_df["estimated_savings"].sum()

        st.metric("Potential Lifecycle Savings", f"${total_lifecycle_savings:,.0f}/mo")

        st.dataframe(
            lifecycle_df,
            column_config={
                "estimated_savings": st.column_config.NumberColumn("Est. Monthly Savings", format="$%.2f"),
            },
            use_container_width=True
        )

        st.markdown("---")
        st.markdown("#### Sample Lifecycle Policy (Terraform)")
        st.code("""
resource "aws_s3_bucket_lifecycle_configuration" "example" {
  bucket = aws_s3_bucket.example.id

  rule {
    id     = "log-retention"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}
        """, language="hcl")

    else:
        st.success("All buckets have lifecycle policies configured!")

    st.info("""
    **Lifecycle Policy Best Practices:**
    - **Logs**: Delete after retention period, archive if needed for compliance
    - **Backups**: Transition to Glacier quickly, Deep Archive for long-term
    - **User Uploads**: Use Intelligent Tiering for unpredictable access
    - **Analytics**: Partition by date, transition older partitions to IA/Glacier
    """)
