"""Streamlit dashboard main application."""

import streamlit as st
import pandas as pd
import numpy as np
import sys
import io
import base64
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(
    page_title="AWS Cost Optimizer",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1F4E79;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .savings-positive {
        color: #28a745;
        font-weight: bold;
    }
    .savings-negative {
        color: #dc3545;
        font-weight: bold;
    }
    .status-implemented {
        background-color: #d4edda;
        color: #155724;
        padding: 2px 8px;
        border-radius: 4px;
    }
    .status-pending {
        background-color: #fff3cd;
        color: #856404;
        padding: 2px 8px;
        border-radius: 4px;
    }
    .status-deferred {
        background-color: #f8d7da;
        color: #721c24;
        padding: 2px 8px;
        border-radius: 4px;
    }
    .sparkline-up {
        color: #dc3545;
    }
    .sparkline-down {
        color: #28a745;
    }
    </style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if "implementation_status" not in st.session_state:
        st.session_state["implementation_status"] = {}
    if "thresholds" not in st.session_state:
        st.session_state["thresholds"] = {
            "cpu_oversized": 40,
            "cpu_undersized": 70,
            "mem_oversized": 50,
            "mem_undersized": 75,
        }


def main():
    init_session_state()

    st.markdown('<div class="main-header">AWS Cost Optimizer Dashboard</div>', unsafe_allow_html=True)

    # Sidebar for data source selection
    with st.sidebar:
        st.header("Data Source")

        source = st.radio(
            "Select data source:",
            ["Upload Report", "Live Analysis"]
        )

        if source == "Upload Report":
            uploaded_file = st.file_uploader(
                "Upload Excel report",
                type=["xlsx", "xls"]
            )
            if uploaded_file:
                st.session_state["report_file"] = uploaded_file
                st.success("Report loaded!")

        else:
            st.subheader("AWS Connection")
            region = st.selectbox(
                "Region",
                ["us-east-1", "us-east-2", "us-west-1", "us-west-2",
                 "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-northeast-1"]
            )

            analysis_months = st.slider(
                "Analysis period (months)",
                min_value=1,
                max_value=12,
                value=3
            )

            st.subheader("Filters")
            gsi_filter = st.text_input("GSI (comma-separated)")
            env_filter = st.multiselect(
                "Environment",
                ["Production", "Staging", "Development", "Test"]
            )

            if st.button("Run Analysis", type="primary"):
                st.session_state["run_analysis"] = True

        # Custom Thresholds Section
        st.divider()
        st.header("Classification Thresholds")

        with st.expander("Adjust Thresholds", expanded=False):
            st.caption("Customize the CPU/Memory thresholds for classification")

            st.markdown("**CPU Thresholds (%)**")
            cpu_oversized = st.slider(
                "Oversized if P95 below:",
                min_value=10, max_value=60,
                value=st.session_state["thresholds"]["cpu_oversized"],
                key="cpu_over_slider"
            )
            cpu_undersized = st.slider(
                "Undersized if P95 above:",
                min_value=50, max_value=95,
                value=st.session_state["thresholds"]["cpu_undersized"],
                key="cpu_under_slider"
            )

            st.markdown("**Memory Thresholds (%)**")
            mem_oversized = st.slider(
                "Oversized if P95 below:",
                min_value=10, max_value=70,
                value=st.session_state["thresholds"]["mem_oversized"],
                key="mem_over_slider"
            )
            mem_undersized = st.slider(
                "Undersized if P95 above:",
                min_value=50, max_value=95,
                value=st.session_state["thresholds"]["mem_undersized"],
                key="mem_under_slider"
            )

            if st.button("Apply Thresholds"):
                st.session_state["thresholds"] = {
                    "cpu_oversized": cpu_oversized,
                    "cpu_undersized": cpu_undersized,
                    "mem_oversized": mem_oversized,
                    "mem_undersized": mem_undersized,
                }
                st.success("Thresholds updated!")
                st.rerun()

        st.divider()
        st.caption("AWS Cost Optimizer v1.1")

    # Main content
    if "report_file" in st.session_state or st.session_state.get("run_analysis"):
        display_dashboard()
    else:
        display_welcome()


def display_welcome():
    """Display welcome page when no data is loaded."""
    col1, col2 = st.columns(2)

    with col1:
        st.header("Welcome!")
        st.markdown("""
        This dashboard helps you:

        - **Analyze** your AWS EC2 resource utilization
        - **Identify** oversized and undersized instances
        - **Calculate** potential cost savings
        - **Generate** rightsizing recommendations

        ### Getting Started

        1. **Upload a report** generated by the CLI tool, or
        2. **Connect to AWS** for live analysis

        Use the sidebar to select your data source.

        ### New Features in v1.1
        - **Custom Thresholds** - Adjust classification cutoffs
        - **Trend Sparklines** - Visual usage trends
        - **Implementation Tracking** - Track recommendation status
        - **PDF Export** - Generate executive summaries
        """)

    with col2:
        st.header("Quick Stats")
        st.info("No data loaded yet. Upload a report or run an analysis to see insights.")


def generate_sparkline(values, width=100, height=20):
    """Generate an SVG sparkline from values."""
    if not values or len(values) < 2:
        return ""

    # Normalize values to fit in the height
    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val if max_val != min_val else 1

    # Create points for the polyline
    points = []
    step = width / (len(values) - 1)
    for i, val in enumerate(values):
        x = i * step
        y = height - ((val - min_val) / range_val * height)
        points.append(f"{x},{y}")

    # Determine color based on trend
    trend_color = "#dc3545" if values[-1] > values[0] else "#28a745"

    svg = f'''<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
        <polyline fill="none" stroke="{trend_color}" stroke-width="2" points="{' '.join(points)}"/>
    </svg>'''

    return svg


def generate_mock_trend_data():
    """Generate mock trend data for sparklines."""
    # In a real implementation, this would come from historical metrics
    return [np.random.uniform(30, 70) for _ in range(10)]


def reclassify_with_thresholds(df):
    """Reclassify servers based on custom thresholds."""
    thresholds = st.session_state["thresholds"]

    def classify_row(row):
        cpu = row.get("cpu_p95")
        mem = row.get("memory_p95")

        if pd.isna(cpu) and pd.isna(mem):
            return "unknown"

        cpu_val = cpu if pd.notna(cpu) else 50
        mem_val = mem if pd.notna(mem) else 50

        # Undersized check
        if cpu_val > thresholds["cpu_undersized"] or mem_val > thresholds["mem_undersized"]:
            return "undersized"

        # Oversized check
        if cpu_val < thresholds["cpu_oversized"] and mem_val < thresholds["mem_oversized"]:
            return "oversized"

        return "right_sized"

    df["classification_custom"] = df.apply(classify_row, axis=1)
    return df


def generate_pdf_report(df, summary_stats):
    """Generate a PDF executive summary."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=colors.HexColor('#1F4E79')
    )
    story.append(Paragraph("AWS Cost Optimization Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Executive Summary
    story.append(Paragraph("Executive Summary", styles['Heading2']))
    story.append(Spacer(1, 10))

    summary_data = [
        ["Metric", "Value"],
        ["Total Servers Analyzed", str(summary_stats['total_servers'])],
        ["Current Monthly Spend", f"${summary_stats['total_spend']:,.2f}"],
        ["Potential Monthly Savings", f"${summary_stats['total_savings']:,.2f}"],
        ["Potential Yearly Savings", f"${summary_stats['total_savings'] * 12:,.2f}"],
        ["Savings Percentage", f"{summary_stats['savings_pct']:.1f}%"],
    ]

    summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))

    # Classification Breakdown
    story.append(Paragraph("Server Classification", styles['Heading2']))
    story.append(Spacer(1, 10))

    class_data = [
        ["Classification", "Count", "Action"],
        ["Oversized", str(summary_stats['oversized']), "Downsize for savings"],
        ["Right-sized", str(summary_stats['right_sized']), "No change needed"],
        ["Undersized", str(summary_stats['undersized']), "Consider upgrade"],
    ]

    class_table = Table(class_data, colWidths=[2*inch, 1*inch, 2.5*inch])
    class_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#d4edda')),  # Oversized - green
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#f8f9fa')),  # Right-sized - gray
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#f8d7da')),  # Undersized - red
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(class_table)
    story.append(Spacer(1, 20))

    # Top 10 Savings Opportunities
    story.append(Paragraph("Top 10 Savings Opportunities", styles['Heading2']))
    story.append(Spacer(1, 10))

    top_savings = df[df["monthly_savings"] > 0].nlargest(10, "monthly_savings")

    if len(top_savings) > 0:
        top_data = [["Server", "Current Type", "Recommended", "Monthly Savings"]]
        for _, row in top_savings.iterrows():
            top_data.append([
                row.get("hostname", row.get("server_id", "N/A"))[:25],
                row.get("instance_type", "N/A"),
                row.get("recommended_type", "N/A") or "N/A",
                f"${row.get('monthly_savings', 0):,.2f}"
            ])

        top_table = Table(top_data, colWidths=[2*inch, 1.3*inch, 1.3*inch, 1.2*inch])
        top_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(top_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def display_dashboard():
    """Display the main dashboard with analysis results."""
    # Load data from uploaded file or session state
    if "report_file" in st.session_state:
        df = pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    else:
        st.warning("Live analysis not yet implemented. Please upload a report.")
        return

    # Reclassify with custom thresholds
    df = reclassify_with_thresholds(df)
    use_custom = st.checkbox("Use custom thresholds for classification", value=False)
    class_col = "classification_custom" if use_custom else "classification"

    # Calculate summary stats
    total_spend = df["current_monthly"].sum() if "current_monthly" in df.columns else 0
    total_savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum() if "monthly_savings" in df.columns else 0

    summary_stats = {
        "total_servers": len(df),
        "total_spend": total_spend,
        "total_savings": total_savings,
        "savings_pct": (total_savings / total_spend * 100) if total_spend > 0 else 0,
        "oversized": len(df[df[class_col] == "oversized"]),
        "right_sized": len(df[df[class_col] == "right_sized"]),
        "undersized": len(df[df[class_col] == "undersized"]),
    }

    # PDF Export Button
    col_header1, col_header2 = st.columns([4, 1])
    with col_header1:
        st.header("Overview")
    with col_header2:
        try:
            pdf_buffer = generate_pdf_report(df, summary_stats)
            st.download_button(
                label="📄 Export PDF",
                data=pdf_buffer,
                file_name=f"cost_optimization_summary_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )
        except ImportError:
            if st.button("📄 Export PDF"):
                st.warning("Install reportlab: `pip install reportlab`")

    # Key Metrics Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Servers",
            value=summary_stats["total_servers"]
        )

    with col2:
        st.metric(
            label="Current Monthly Spend",
            value=f"${summary_stats['total_spend']:,.0f}"
        )

    with col3:
        st.metric(
            label="Potential Monthly Savings",
            value=f"${summary_stats['total_savings']:,.0f}",
            delta=f"-{summary_stats['savings_pct']:.1f}%" if summary_stats['total_spend'] > 0 else None,
            delta_color="inverse"
        )

    with col4:
        st.metric(
            label="Oversized Instances",
            value=summary_stats["oversized"]
        )

    st.divider()

    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs([
        "Server Analysis",
        "Recommendations",
        "Cost Breakdown",
        "Contention"
    ])

    with tab1:
        display_server_analysis(df, class_col)

    with tab2:
        display_recommendations(df, class_col)

    with tab3:
        display_cost_breakdown(df)

    with tab4:
        display_contention(df)


def display_server_analysis(df, class_col="classification"):
    """Display server analysis tab with sparklines."""
    import plotly.express as px

    st.subheader("Server Classification")

    if class_col not in df.columns:
        st.warning("Classification data not available")
        return

    # Classification pie chart
    col1, col2 = st.columns([1, 2])

    with col1:
        class_counts = df[class_col].value_counts()
        fig = px.pie(
            values=class_counts.values,
            names=class_counts.index,
            color=class_counts.index,
            color_discrete_map={
                "oversized": "#28a745",
                "right_sized": "#6c757d",
                "undersized": "#dc3545",
                "unknown": "#ffc107"
            }
        )
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Filter options
        selected_class = st.multiselect(
            "Filter by classification:",
            options=df[class_col].unique(),
            default=list(df[class_col].unique())
        )

        filtered_df = df[df[class_col].isin(selected_class)].copy()

        # Add trend indicators (mock data for demo)
        filtered_df["cpu_trend"] = filtered_df["cpu_p95"].apply(
            lambda x: "📈" if np.random.random() > 0.5 else "📉" if pd.notna(x) else ""
        )
        filtered_df["mem_trend"] = filtered_df["memory_p95"].apply(
            lambda x: "📈" if np.random.random() > 0.5 else "📉" if pd.notna(x) else ""
        )

        display_cols = ["hostname", "instance_type", "cpu_p95", "cpu_trend", "memory_p95", "mem_trend", class_col]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        st.dataframe(
            filtered_df[available_cols],
            use_container_width=True,
            height=300,
            column_config={
                "cpu_p95": st.column_config.NumberColumn("CPU P95 %", format="%.1f"),
                "memory_p95": st.column_config.NumberColumn("Mem P95 %", format="%.1f"),
                "cpu_trend": st.column_config.TextColumn("CPU Trend", width="small"),
                "mem_trend": st.column_config.TextColumn("Mem Trend", width="small"),
            }
        )

    # CPU vs Memory scatter plot with threshold lines
    st.subheader("Resource Utilization")

    thresholds = st.session_state["thresholds"]

    if "cpu_p95" in df.columns and "memory_p95" in df.columns:
        fig = px.scatter(
            df,
            x="cpu_p95",
            y="memory_p95",
            color=class_col,
            hover_data=["hostname", "instance_type"],
            color_discrete_map={
                "oversized": "#28a745",
                "right_sized": "#6c757d",
                "undersized": "#dc3545",
                "unknown": "#ffc107"
            },
            labels={"cpu_p95": "CPU P95 (%)", "memory_p95": "Memory P95 (%)"}
        )

        # Add threshold lines based on custom thresholds
        fig.add_hline(y=thresholds["mem_undersized"], line_dash="dash", line_color="red",
                      annotation_text=f"Mem Undersized ({thresholds['mem_undersized']}%)")
        fig.add_hline(y=thresholds["mem_oversized"], line_dash="dash", line_color="green",
                      annotation_text=f"Mem Oversized ({thresholds['mem_oversized']}%)")
        fig.add_vline(x=thresholds["cpu_undersized"], line_dash="dash", line_color="red",
                      annotation_text=f"CPU Undersized ({thresholds['cpu_undersized']}%)")
        fig.add_vline(x=thresholds["cpu_oversized"], line_dash="dash", line_color="green",
                      annotation_text=f"CPU Oversized ({thresholds['cpu_oversized']}%)")

        fig.update_layout(height=450)
        st.plotly_chart(fig, use_container_width=True)


def display_recommendations(df, class_col="classification"):
    """Display recommendations tab with implementation tracking."""
    import plotly.express as px

    st.subheader("Rightsizing Recommendations")

    # Filter to servers with recommendations
    if "recommended_type" not in df.columns:
        st.warning("Recommendation data not available")
        return

    recs_df = df[df["recommended_type"].notna()].copy()

    if len(recs_df) == 0:
        st.info("All servers are appropriately sized!")
        return

    # Sort by savings
    recs_df = recs_df.sort_values("monthly_savings", ascending=False)

    # Implementation Status Tracking
    st.markdown("### Implementation Tracking")

    col1, col2, col3 = st.columns(3)

    # Count by status
    statuses = st.session_state.get("implementation_status", {})
    implemented = sum(1 for s in statuses.values() if s == "Implemented")
    pending = sum(1 for s in statuses.values() if s == "Pending")
    deferred = sum(1 for s in statuses.values() if s == "Deferred")
    not_set = len(recs_df) - len(statuses)

    with col1:
        st.metric("Implemented", implemented, delta=None)
    with col2:
        st.metric("Pending", pending + not_set)
    with col3:
        st.metric("Deferred", deferred)

    st.markdown("### Recommendations")

    # Add status column
    def get_status(server_id):
        return st.session_state.get("implementation_status", {}).get(server_id, "Pending")

    recs_df["status"] = recs_df["server_id"].apply(get_status)

    # Editable table for status
    edited_df = st.data_editor(
        recs_df[["hostname", "instance_type", "recommended_type", "monthly_savings",
                 "confidence", "risk_level", "status"]].head(20),
        column_config={
            "hostname": st.column_config.TextColumn("Server", disabled=True),
            "instance_type": st.column_config.TextColumn("Current Type", disabled=True),
            "recommended_type": st.column_config.TextColumn("Recommended", disabled=True),
            "monthly_savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f", disabled=True),
            "confidence": st.column_config.ProgressColumn("Confidence", format="%.0f%%", min_value=0, max_value=1),
            "risk_level": st.column_config.TextColumn("Risk", disabled=True),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=["Pending", "Implemented", "Deferred"],
                required=True
            )
        },
        use_container_width=True,
        hide_index=True,
        key="recommendations_editor"
    )

    # Save status changes
    if st.button("Save Status Changes"):
        for idx, row in edited_df.iterrows():
            server_id = recs_df.iloc[idx]["server_id"]
            st.session_state["implementation_status"][server_id] = row["status"]
        st.success("Status changes saved!")
        st.rerun()

    # Savings bar chart
    st.markdown("### Savings by Server")

    top_20 = recs_df.head(20)
    fig = px.bar(
        top_20,
        x="hostname" if "hostname" in top_20.columns else "server_id",
        y="monthly_savings",
        color=class_col if class_col in top_20.columns else None,
        color_discrete_map={
            "oversized": "#28a745",
            "undersized": "#dc3545"
        }
    )
    fig.update_layout(height=400, xaxis_tickangle=45)
    st.plotly_chart(fig, use_container_width=True)


def display_cost_breakdown(df):
    """Display cost breakdown tab."""
    import plotly.express as px
    import plotly.graph_objects as go

    st.subheader("Cost Analysis")

    if "current_monthly" not in df.columns:
        st.warning("Cost data not available")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Current vs. Optimized Spend")

        current = df["current_monthly"].sum()
        savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum()
        optimized = current - savings

        fig = go.Figure(data=[
            go.Bar(name='Current', x=['Monthly Spend'], y=[current], marker_color='#6c757d'),
            go.Bar(name='Optimized', x=['Monthly Spend'], y=[optimized], marker_color='#28a745')
        ])
        fig.update_layout(height=300, barmode='group')
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("### Cost by Instance Type")

        if "instance_type" in df.columns:
            by_type = df.groupby("instance_type")["current_monthly"].sum().sort_values(ascending=False).head(10)

            fig = px.pie(
                values=by_type.values,
                names=by_type.index
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

    # 12-month projection
    st.markdown("### 12-Month Savings Projection")

    savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum()
    months = list(range(1, 13))
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cumulative = [savings * m for m in months]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=month_names,
        y=cumulative,
        mode='lines+markers',
        fill='tozeroy',
        fillcolor='rgba(40, 167, 69, 0.2)',
        line=dict(color='#28a745', width=3)
    ))
    fig.update_layout(
        height=300,
        xaxis_title="Month",
        yaxis_title="Cumulative Savings ($)",
        yaxis_tickformat="$,.0f"
    )
    st.plotly_chart(fig, use_container_width=True)


def display_contention(df):
    """Display contention analysis tab."""
    st.subheader("Resource Contention")

    if "has_contention" not in df.columns:
        st.warning("Contention data not available")
        return

    contention_df = df[df["has_contention"] == True]

    if len(contention_df) == 0:
        st.success("No resource contention detected!")
        return

    st.warning(f"Found {len(contention_df)} servers with resource contention")

    # Contention table
    display_cols = ["hostname", "instance_type", "contention_events",
                   "contention_hours", "cpu_p95", "memory_p95"]
    available_cols = [c for c in display_cols if c in contention_df.columns]

    st.dataframe(
        contention_df[available_cols].sort_values("contention_events", ascending=False),
        use_container_width=True,
        column_config={
            "contention_events": st.column_config.NumberColumn("Events"),
            "contention_hours": st.column_config.NumberColumn("Hours", format="%.1f"),
            "cpu_p95": st.column_config.NumberColumn("CPU P95 %", format="%.1f"),
            "memory_p95": st.column_config.NumberColumn("Mem P95 %", format="%.1f"),
        }
    )


if __name__ == "__main__":
    main()
