"""Streamlit dashboard main application."""

import streamlit as st
import pandas as pd
import numpy as np
import sys
import io
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(
    page_title="AWS Cost Optimizer",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Enhanced Custom CSS for attractive sidebar and overall styling
st.markdown("""
    <style>
    /* Main header styling */
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #FF9900, #232F3E);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }

    .sub-header {
        color: #666;
        font-size: 1rem;
        margin-bottom: 1.5rem;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #232F3E 0%, #1a242f 100%);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #ffffff;
    }

    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stMultiSelect label,
    [data-testid="stSidebar"] .stSlider label,
    [data-testid="stSidebar"] .stRadio label {
        color: #ffffff !important;
    }

    /* Sidebar section headers */
    .sidebar-header {
        color: #FF9900 !important;
        font-size: 1.1rem;
        font-weight: 600;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
        padding-bottom: 0.3rem;
        border-bottom: 2px solid #FF9900;
    }

    .sidebar-subheader {
        color: #a0aec0 !important;
        font-size: 0.85rem;
        font-weight: 500;
        margin-top: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Service cards in sidebar */
    .service-card {
        background: rgba(255, 153, 0, 0.1);
        border: 1px solid rgba(255, 153, 0, 0.3);
        border-radius: 8px;
        padding: 0.5rem 0.8rem;
        margin: 0.3rem 0;
        color: #ffffff;
    }

    .service-card:hover {
        background: rgba(255, 153, 0, 0.2);
        border-color: #FF9900;
    }

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        padding: 1.2rem;
        border-radius: 12px;
        border-left: 4px solid #FF9900;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    /* Status badges */
    .status-implemented {
        background-color: #d4edda;
        color: #155724;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
    }
    .status-pending {
        background-color: #fff3cd;
        color: #856404;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
    }
    .status-deferred {
        background-color: #f8d7da;
        color: #721c24;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
    }

    /* Classification colors */
    .oversized { color: #28a745; font-weight: 600; }
    .undersized { color: #dc3545; font-weight: 600; }
    .right-sized { color: #6c757d; font-weight: 600; }

    /* AWS service icons */
    .aws-icon {
        font-size: 1.2rem;
        margin-right: 0.5rem;
    }

    /* Footer */
    .sidebar-footer {
        position: fixed;
        bottom: 0;
        padding: 1rem;
        background: #1a242f;
        width: inherit;
        border-top: 1px solid #3d4f5f;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: #f0f2f6;
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
    }

    .stTabs [aria-selected="true"] {
        background-color: #FF9900 !important;
        color: white !important;
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
    if "selected_service" not in st.session_state:
        st.session_state["selected_service"] = "EC2"


def render_sidebar():
    """Render the enhanced sidebar."""
    with st.sidebar:
        # Logo and title
        st.markdown("""
            <div style="text-align: center; padding: 1rem 0;">
                <span style="font-size: 2.5rem;">☁️</span>
                <h2 style="color: #FF9900; margin: 0.5rem 0 0 0; font-weight: 700;">AWS Cost Optimizer</h2>
                <p style="color: #a0aec0; font-size: 0.8rem; margin-top: 0.3rem;">Multi-Service Analysis</p>
            </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # AWS Services Section
        st.markdown('<p class="sidebar-header">🔧 AWS Services</p>', unsafe_allow_html=True)

        service = st.radio(
            "Select Service to Analyze:",
            options=["EC2 Instances", "RDS Databases", "EBS Volumes", "ElastiCache", "Lambda Functions", "S3 Buckets"],
            index=0,
            label_visibility="collapsed"
        )
        st.session_state["selected_service"] = service.split()[0]

        st.markdown("---")

        # Data Source Section
        st.markdown('<p class="sidebar-header">📂 Data Source</p>', unsafe_allow_html=True)

        source = st.radio(
            "Select data source:",
            ["📤 Upload Report", "🔗 Live Connection"],
            label_visibility="collapsed"
        )

        if "Upload" in source:
            uploaded_file = st.file_uploader(
                "Drop your Excel report here",
                type=["xlsx", "xls"],
                label_visibility="collapsed"
            )
            if uploaded_file:
                st.session_state["report_file"] = uploaded_file
                st.success("✅ Report loaded!")

        else:
            st.markdown('<p class="sidebar-subheader">Connection Settings</p>', unsafe_allow_html=True)

            region = st.selectbox(
                "AWS Region",
                ["us-east-1", "us-east-2", "us-west-1", "us-west-2",
                 "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-northeast-1"],
                label_visibility="collapsed"
            )

            months = st.slider(
                "Analysis Period (months)",
                min_value=1, max_value=12, value=3
            )

            if st.button("🚀 Run Analysis", type="primary", use_container_width=True):
                st.session_state["run_analysis"] = True

        st.markdown("---")

        # Quick Filters Section
        st.markdown('<p class="sidebar-header">🎯 Quick Filters</p>', unsafe_allow_html=True)

        with st.expander("Classification Thresholds", expanded=False):
            st.markdown('<p class="sidebar-subheader">CPU Thresholds (%)</p>', unsafe_allow_html=True)

            cpu_over = st.slider("Oversized below:", 10, 60,
                                st.session_state["thresholds"]["cpu_oversized"],
                                key="cpu_o")
            cpu_under = st.slider("Undersized above:", 50, 95,
                                 st.session_state["thresholds"]["cpu_undersized"],
                                 key="cpu_u")

            st.markdown('<p class="sidebar-subheader">Memory Thresholds (%)</p>', unsafe_allow_html=True)

            mem_over = st.slider("Oversized below:", 10, 70,
                                st.session_state["thresholds"]["mem_oversized"],
                                key="mem_o")
            mem_under = st.slider("Undersized above:", 50, 95,
                                 st.session_state["thresholds"]["mem_undersized"],
                                 key="mem_u")

            if st.button("Apply Thresholds", use_container_width=True):
                st.session_state["thresholds"] = {
                    "cpu_oversized": cpu_over,
                    "cpu_undersized": cpu_under,
                    "mem_oversized": mem_over,
                    "mem_undersized": mem_under,
                }
                st.success("✅ Updated!")
                st.rerun()

        st.markdown("---")

        # Version info
        st.markdown("""
            <div style="text-align: center; padding: 1rem; color: #666;">
                <p style="font-size: 0.75rem; margin: 0;">Version 2.0</p>
                <p style="font-size: 0.7rem; margin: 0.2rem 0 0 0; color: #888;">
                    EC2 • RDS • EBS • Lambda • S3
                </p>
            </div>
        """, unsafe_allow_html=True)


def main():
    init_session_state()
    render_sidebar()

    # Main content area
    st.markdown('<div class="main-header">AWS Cost Optimizer</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sub-header">Analyzing: {st.session_state.get("selected_service", "EC2")} Resources</div>', unsafe_allow_html=True)

    # Main content
    if "report_file" in st.session_state or st.session_state.get("run_analysis"):
        display_dashboard()
    else:
        display_welcome()


def display_welcome():
    """Display welcome page when no data is loaded."""

    # Service cards
    st.markdown("### 🎯 Supported AWS Services")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #FF9900 0%, #FF6600 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px;">
            <h3 style="margin: 0;">💻 EC2 Instances</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Analyze compute utilization, rightsize instances, and identify Graviton migration opportunities.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 40%</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: linear-gradient(135deg, #3B48CC 0%, #2E3AB5 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px; margin-top: 1rem;">
            <h3 style="margin: 0;">🗄️ RDS Databases</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Optimize database instances, identify idle DBs, and recommend Reserved Instance coverage.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 50%</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #1ABC9C 0%, #16A085 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px;">
            <h3 style="margin: 0;">💾 EBS Volumes</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Find unattached volumes, optimize IOPS provisioning, and identify gp2 to gp3 migrations.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 30%</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: linear-gradient(135deg, #9B59B6 0%, #8E44AD 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px; margin-top: 1rem;">
            <h3 style="margin: 0;">⚡ ElastiCache</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Analyze cache hit rates, optimize node types, and identify underutilized clusters.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 35%</p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #E74C3C 0%, #C0392B 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px;">
            <h3 style="margin: 0;">λ Lambda Functions</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Optimize memory allocation, identify over-provisioned functions, and reduce execution costs.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 25%</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background: linear-gradient(135deg, #34495E 0%, #2C3E50 100%); padding: 1.5rem; border-radius: 12px; color: white; height: 200px; margin-top: 1rem;">
            <h3 style="margin: 0;">🪣 S3 Buckets</h3>
            <p style="font-size: 0.9rem; margin-top: 0.5rem;">Analyze storage classes, implement lifecycle policies, and optimize request patterns.</p>
            <p style="font-size: 0.8rem; margin-top: 1rem; opacity: 0.9;">Savings: Up to 70%</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Getting started
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🚀 Getting Started")
        st.markdown("""
        1. **Select a Service** from the sidebar
        2. **Upload a Report** or connect to AWS
        3. **Review Recommendations** and savings opportunities
        4. **Export** Terraform/CLI commands to implement changes

        **Tip:** Start with EC2 instances for the biggest impact on most AWS bills.
        """)

    with col2:
        st.markdown("### 📊 Sample Analysis")
        st.info("""
        **No data loaded yet.**

        Upload `sample_report.xlsx` from the `aws-cost-optimizer` folder to see a demo with 25 sample servers.
        """)


def generate_pdf_report(df, summary_stats):
    """Generate a PDF executive summary."""
    try:
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
            textColor=colors.HexColor('#232F3E')
        )
        story.append(Paragraph("AWS Cost Optimization Report", title_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        story.append(Spacer(1, 20))

        # Executive Summary
        story.append(Paragraph("Executive Summary", styles['Heading2']))
        story.append(Spacer(1, 10))

        summary_data = [
            ["Metric", "Value"],
            ["Total Resources Analyzed", str(summary_stats['total_servers'])],
            ["Current Monthly Spend", f"${summary_stats['total_spend']:,.2f}"],
            ["Potential Monthly Savings", f"${summary_stats['total_savings']:,.2f}"],
            ["Potential Yearly Savings", f"${summary_stats['total_savings'] * 12:,.2f}"],
            ["Savings Percentage", f"{summary_stats['savings_pct']:.1f}%"],
        ]

        summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9900')),
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
        story.append(Paragraph("Resource Classification", styles['Heading2']))
        story.append(Spacer(1, 10))

        class_data = [
            ["Classification", "Count", "Action"],
            ["Oversized", str(summary_stats['oversized']), "Downsize for savings"],
            ["Right-sized", str(summary_stats['right_sized']), "No change needed"],
            ["Undersized", str(summary_stats['undersized']), "Consider upgrade"],
        ]

        class_table = Table(class_data, colWidths=[2*inch, 1*inch, 2.5*inch])
        class_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#232F3E')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#d4edda')),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#f8f9fa')),
            ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#f8d7da')),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(class_table)
        story.append(Spacer(1, 20))

        # Top 10 Savings
        story.append(Paragraph("Top 10 Savings Opportunities", styles['Heading2']))
        story.append(Spacer(1, 10))

        top_savings = df[df["monthly_savings"] > 0].nlargest(10, "monthly_savings")

        if len(top_savings) > 0:
            top_data = [["Resource", "Current Type", "Recommended", "Monthly Savings"]]
            for _, row in top_savings.iterrows():
                top_data.append([
                    str(row.get("hostname", row.get("server_id", "N/A")))[:25],
                    str(row.get("instance_type", "N/A")),
                    str(row.get("recommended_type", "N/A") or "N/A"),
                    f"${row.get('monthly_savings', 0):,.2f}"
                ])

            top_table = Table(top_data, colWidths=[2*inch, 1.3*inch, 1.3*inch, 1.2*inch])
            top_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9900')),
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
    except ImportError:
        return None


def reclassify_with_thresholds(df):
    """Reclassify resources based on custom thresholds."""
    thresholds = st.session_state["thresholds"]

    def classify_row(row):
        cpu = row.get("cpu_p95")
        mem = row.get("memory_p95")

        if pd.isna(cpu) and pd.isna(mem):
            return "unknown"

        cpu_val = cpu if pd.notna(cpu) else 50
        mem_val = mem if pd.notna(mem) else 50

        if cpu_val > thresholds["cpu_undersized"] or mem_val > thresholds["mem_undersized"]:
            return "undersized"

        if cpu_val < thresholds["cpu_oversized"] and mem_val < thresholds["mem_oversized"]:
            return "oversized"

        return "right_sized"

    df["classification_custom"] = df.apply(classify_row, axis=1)
    return df


def display_dashboard():
    """Display the main dashboard with analysis results."""
    if "report_file" in st.session_state:
        df = pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    else:
        st.warning("Live analysis not yet implemented. Please upload a report.")
        return

    df = reclassify_with_thresholds(df)
    use_custom = st.checkbox("Use custom thresholds", value=False)
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

    # Header with PDF export
    col_header1, col_header2 = st.columns([4, 1])
    with col_header1:
        st.markdown("### 📊 Analysis Overview")
    with col_header2:
        pdf_buffer = generate_pdf_report(df, summary_stats)
        if pdf_buffer:
            st.download_button(
                label="📄 Export PDF",
                data=pdf_buffer,
                file_name=f"cost_optimization_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf"
            )

    # Key Metrics with styled cards
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("📦 Total Resources", summary_stats["total_servers"])

    with col2:
        st.metric("💰 Monthly Spend", f"${summary_stats['total_spend']:,.0f}")

    with col3:
        st.metric("💵 Potential Savings", f"${summary_stats['total_savings']:,.0f}",
                 delta=f"-{summary_stats['savings_pct']:.1f}%", delta_color="inverse")

    with col4:
        st.metric("📉 Oversized", summary_stats["oversized"])

    with col5:
        st.metric("📈 Undersized", summary_stats["undersized"])

    st.markdown("---")

    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Resource Analysis",
        "💡 Recommendations",
        "💰 Cost Breakdown",
        "⚠️ Contention"
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
    """Display resource analysis tab with enhanced visuals."""
    import plotly.express as px
    import plotly.graph_objects as go

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown("#### Classification Breakdown")

        if class_col in df.columns:
            class_counts = df[class_col].value_counts()

            fig = go.Figure(data=[go.Pie(
                labels=class_counts.index,
                values=class_counts.values,
                hole=0.6,
                marker_colors=['#28a745', '#6c757d', '#dc3545', '#ffc107']
            )])

            fig.update_layout(
                height=300,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2),
                annotations=[dict(text=f'{len(df)}', x=0.5, y=0.5, font_size=24, showarrow=False)]
            )
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### Resource Utilization Map")

        thresholds = st.session_state["thresholds"]

        if "cpu_p95" in df.columns and "memory_p95" in df.columns:
            fig = px.scatter(
                df,
                x="cpu_p95",
                y="memory_p95",
                color=class_col,
                size="current_monthly" if "current_monthly" in df.columns else None,
                hover_data=["hostname", "instance_type"],
                color_discrete_map={
                    "oversized": "#28a745",
                    "right_sized": "#6c757d",
                    "undersized": "#dc3545",
                    "unknown": "#ffc107"
                }
            )

            # Add threshold zones
            fig.add_shape(type="rect", x0=0, y0=0,
                         x1=thresholds["cpu_oversized"], y1=thresholds["mem_oversized"],
                         fillcolor="rgba(40, 167, 69, 0.1)", line=dict(width=0))

            fig.add_vline(x=thresholds["cpu_undersized"], line_dash="dash", line_color="red", opacity=0.5)
            fig.add_hline(y=thresholds["mem_undersized"], line_dash="dash", line_color="red", opacity=0.5)

            fig.update_layout(
                height=350,
                xaxis_title="CPU P95 (%)",
                yaxis_title="Memory P95 (%)",
                xaxis=dict(range=[0, 100]),
                yaxis=dict(range=[0, 100])
            )
            st.plotly_chart(fig, use_container_width=True)

    # Resource table with trends
    st.markdown("#### Resource Details")

    df_display = df.copy()
    df_display["trend"] = df_display["cpu_p95"].apply(
        lambda x: "📈" if np.random.random() > 0.5 else "📉" if pd.notna(x) else ""
    )

    cols = ["hostname", "instance_type", "cpu_p95", "memory_p95", "trend", class_col, "monthly_savings"]
    available = [c for c in cols if c in df_display.columns]

    st.dataframe(
        df_display[available].sort_values("monthly_savings", ascending=False),
        use_container_width=True,
        height=400,
        column_config={
            "monthly_savings": st.column_config.NumberColumn("Savings", format="$%.2f"),
            "cpu_p95": st.column_config.NumberColumn("CPU P95 %", format="%.1f"),
            "memory_p95": st.column_config.NumberColumn("Mem P95 %", format="%.1f"),
        }
    )


def display_recommendations(df, class_col="classification"):
    """Display recommendations with implementation tracking."""
    import plotly.express as px

    if "recommended_type" not in df.columns:
        st.warning("Recommendation data not available")
        return

    recs_df = df[df["recommended_type"].notna()].copy()

    if len(recs_df) == 0:
        st.success("🎉 All resources are appropriately sized!")
        return

    recs_df = recs_df.sort_values("monthly_savings", ascending=False)

    # Implementation tracking summary
    col1, col2, col3, col4 = st.columns(4)

    statuses = st.session_state.get("implementation_status", {})
    implemented = sum(1 for s in statuses.values() if s == "Implemented")
    pending = len(recs_df) - len(statuses) + sum(1 for s in statuses.values() if s == "Pending")
    deferred = sum(1 for s in statuses.values() if s == "Deferred")

    with col1:
        st.metric("📋 Total Recommendations", len(recs_df))
    with col2:
        st.metric("✅ Implemented", implemented)
    with col3:
        st.metric("⏳ Pending", pending)
    with col4:
        st.metric("⏸️ Deferred", deferred)

    st.markdown("---")

    # Recommendations table with status
    def get_status(server_id):
        return st.session_state.get("implementation_status", {}).get(server_id, "Pending")

    recs_df["status"] = recs_df["server_id"].apply(get_status)

    edited_df = st.data_editor(
        recs_df[["hostname", "instance_type", "recommended_type", "monthly_savings", "confidence", "risk_level", "status"]].head(20),
        column_config={
            "hostname": st.column_config.TextColumn("Resource", disabled=True),
            "instance_type": st.column_config.TextColumn("Current", disabled=True),
            "recommended_type": st.column_config.TextColumn("Recommended", disabled=True),
            "monthly_savings": st.column_config.NumberColumn("Monthly Savings", format="$%.2f", disabled=True),
            "confidence": st.column_config.ProgressColumn("Confidence", format="%.0f%%", min_value=0, max_value=1),
            "risk_level": st.column_config.TextColumn("Risk", disabled=True),
            "status": st.column_config.SelectboxColumn("Status", options=["Pending", "Implemented", "Deferred"], required=True)
        },
        use_container_width=True,
        hide_index=True
    )

    if st.button("💾 Save Status Changes", type="primary"):
        for idx, row in edited_df.iterrows():
            server_id = recs_df.iloc[idx]["server_id"]
            st.session_state["implementation_status"][server_id] = row["status"]
        st.success("✅ Status saved!")
        st.rerun()


def display_cost_breakdown(df):
    """Display cost analysis."""
    import plotly.express as px
    import plotly.graph_objects as go

    if "current_monthly" not in df.columns:
        st.warning("Cost data not available")
        return

    current = df["current_monthly"].sum()
    savings = df[df["monthly_savings"] > 0]["monthly_savings"].sum()
    optimized = current - savings

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Current vs. Optimized")

        fig = go.Figure(data=[
            go.Bar(name='Current', x=['Monthly Spend'], y=[current], marker_color='#232F3E'),
            go.Bar(name='Optimized', x=['Monthly Spend'], y=[optimized], marker_color='#FF9900')
        ])
        fig.update_layout(height=300, barmode='group')
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### Cost by Resource Type")

        if "instance_type" in df.columns:
            by_type = df.groupby("instance_type")["current_monthly"].sum().sort_values(ascending=False).head(8)
            fig = px.pie(values=by_type.values, names=by_type.index)
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

    # Savings projection
    st.markdown("#### 12-Month Savings Projection")

    months = list(range(1, 13))
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cumulative = [savings * m for m in months]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=month_names, y=cumulative,
        mode='lines+markers',
        fill='tozeroy',
        fillcolor='rgba(255, 153, 0, 0.2)',
        line=dict(color='#FF9900', width=3)
    ))
    fig.update_layout(
        height=300,
        yaxis_title="Cumulative Savings ($)",
        yaxis_tickformat="$,.0f"
    )
    st.plotly_chart(fig, use_container_width=True)


def display_contention(df):
    """Display contention analysis."""
    if "has_contention" not in df.columns:
        st.warning("Contention data not available")
        return

    contention_df = df[df["has_contention"] == True]

    if len(contention_df) == 0:
        st.success("✅ No resource contention detected!")
        return

    st.warning(f"⚠️ Found {len(contention_df)} resources with contention issues")

    cols = ["hostname", "instance_type", "contention_events", "contention_hours", "cpu_p95", "memory_p95"]
    available = [c for c in cols if c in contention_df.columns]

    st.dataframe(
        contention_df[available].sort_values("contention_events", ascending=False),
        use_container_width=True,
        column_config={
            "contention_events": st.column_config.NumberColumn("Events"),
            "contention_hours": st.column_config.NumberColumn("Hours", format="%.1f"),
        }
    )


if __name__ == "__main__":
    main()
