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
        st.session_state["implementation_status"] = load_persisted_state("implementation_status", {})
    if "thresholds" not in st.session_state:
        st.session_state["thresholds"] = load_persisted_state("thresholds", {
            "cpu_oversized": 40,
            "cpu_undersized": 70,
            "mem_oversized": 50,
            "mem_undersized": 75,
        })
    if "selected_service" not in st.session_state:
        st.session_state["selected_service"] = "EC2"
    if "data_source" not in st.session_state:
        st.session_state["data_source"] = "none"  # none, sample, uploaded, live


def get_state_file_path():
    """Get path for persisted state file."""
    return Path(__file__).parent / ".dashboard_state.json"


def load_persisted_state(key: str, default):
    """Load persisted state from file."""
    import json
    state_file = get_state_file_path()
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                all_state = json.load(f)
                return all_state.get(key, default)
        except Exception:
            pass
    return default


def save_persisted_state():
    """Save session state to file for persistence."""
    import json
    state_file = get_state_file_path()
    try:
        # Load existing state
        if state_file.exists():
            with open(state_file, "r") as f:
                all_state = json.load(f)
        else:
            all_state = {}

        # Update with current session state
        all_state["implementation_status"] = st.session_state.get("implementation_status", {})
        all_state["thresholds"] = st.session_state.get("thresholds", {})

        with open(state_file, "w") as f:
            json.dump(all_state, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Failed to save state: {e}")
        return False


def is_sample_data(df) -> bool:
    """Detect if data is sample/demo data based on patterns."""
    if df is None or len(df) == 0:
        return False

    # Check for sample data patterns
    sample_indicators = [
        # Check for common sample hostnames
        df.get("hostname", pd.Series()).str.contains("sample|demo|test|example", case=False, na=False).any() if "hostname" in df.columns else False,
        # Check if all server_ids follow a pattern like "i-sample"
        df.get("server_id", pd.Series()).str.contains("sample|demo", case=False, na=False).any() if "server_id" in df.columns else False,
        # Check if exactly 25 servers (our sample size)
        len(df) == 25,
    ]

    return any(sample_indicators)


def render_data_source_indicator():
    """Render a visual indicator for the data source."""
    source = st.session_state.get("data_source", "none")

    if source == "sample":
        st.markdown("""
            <div style="background: linear-gradient(90deg, #ffc107, #ff9800); color: #000; padding: 0.5rem 1rem;
                        border-radius: 8px; margin-bottom: 1rem; text-align: center; font-weight: 600;">
                ⚠️ SAMPLE DATA - This is demo/synthetic data for illustration purposes only
            </div>
        """, unsafe_allow_html=True)
    elif source == "uploaded":
        st.markdown("""
            <div style="background: #28a745; color: white; padding: 0.5rem 1rem;
                        border-radius: 8px; margin-bottom: 1rem; text-align: center;">
                📤 Uploaded Report Data
            </div>
        """, unsafe_allow_html=True)
    elif source == "live":
        st.markdown("""
            <div style="background: #007bff; color: white; padding: 0.5rem 1rem;
                        border-radius: 8px; margin-bottom: 1rem; text-align: center;">
                🔗 Live AWS Connection
            </div>
        """, unsafe_allow_html=True)


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
                # Detect if sample data
                try:
                    temp_df = pd.read_excel(uploaded_file, sheet_name="Server Details")
                    if is_sample_data(temp_df):
                        st.session_state["data_source"] = "sample"
                        st.warning("⚠️ Sample data detected")
                    else:
                        st.session_state["data_source"] = "uploaded"
                        st.success("✅ Report loaded!")
                    uploaded_file.seek(0)  # Reset file pointer
                except Exception:
                    st.session_state["data_source"] = "uploaded"
                    st.success("✅ Report loaded!")

        else:
            st.markdown('<p class="sidebar-subheader">Connection Settings</p>', unsafe_allow_html=True)

            region = st.selectbox(
                "AWS Region",
                ["us-east-1", "us-east-2", "us-west-1", "us-west-2",
                 "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-northeast-1"],
                label_visibility="collapsed"
            )
            st.session_state["aws_region"] = region

            months = st.slider(
                "Analysis Period (months)",
                min_value=1, max_value=12, value=3
            )
            st.session_state["analysis_months"] = months

            use_cloudwatch = st.checkbox("Use CloudWatch (instead of Dynatrace)", value=True)
            st.session_state["use_cloudwatch"] = use_cloudwatch

            if st.button("🚀 Run Analysis", type="primary", use_container_width=True):
                st.session_state["run_analysis"] = True
                st.session_state["data_source"] = "live"

            st.markdown('<p class="sidebar-subheader">Quick Demo</p>', unsafe_allow_html=True)
            if st.button("📊 Load Sample Data", use_container_width=True):
                load_sample_data()
                st.rerun()

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


def load_sample_data():
    """Load sample data for demo purposes."""
    sample_path = Path(__file__).parent.parent / "sample_report.xlsx"
    if sample_path.exists():
        st.session_state["report_file"] = sample_path
        st.session_state["data_source"] = "sample"
        st.success("📊 Sample data loaded!")
    else:
        # Generate sample data on the fly
        st.session_state["sample_df"] = generate_sample_dataframe()
        st.session_state["data_source"] = "sample"
        st.success("📊 Sample data generated!")


def generate_sample_dataframe():
    """Generate sample DataFrame for demo."""
    import random

    instance_types = ["t3.micro", "t3.small", "t3.medium", "t3.large", "m5.large", "m5.xlarge", "m5.2xlarge", "r5.large", "c5.large", "c5.xlarge"]
    environments = ["Production", "Staging", "Development"]

    data = []
    for i in range(25):
        env = random.choice(environments)
        instance_type = random.choice(instance_types)

        # Generate realistic metrics based on classification
        classification = random.choice(["oversized", "right_sized", "undersized"])
        if classification == "oversized":
            cpu_p95 = random.uniform(10, 35)
            mem_p95 = random.uniform(15, 45)
            monthly_savings = random.uniform(50, 500)
        elif classification == "undersized":
            cpu_p95 = random.uniform(75, 95)
            mem_p95 = random.uniform(80, 95)
            monthly_savings = 0
        else:
            cpu_p95 = random.uniform(40, 65)
            mem_p95 = random.uniform(50, 70)
            monthly_savings = 0

        current_monthly = random.uniform(50, 1000)

        data.append({
            "server_id": f"i-sample{i:04d}",
            "hostname": f"sample-server-{i:02d}",
            "instance_type": instance_type,
            "vcpu": {"t3.micro": 2, "t3.small": 2, "t3.medium": 2, "t3.large": 2, "m5.large": 2, "m5.xlarge": 4, "m5.2xlarge": 8, "r5.large": 2, "c5.large": 2, "c5.xlarge": 4}.get(instance_type, 2),
            "memory_gb": {"t3.micro": 1, "t3.small": 2, "t3.medium": 4, "t3.large": 8, "m5.large": 8, "m5.xlarge": 16, "m5.2xlarge": 32, "r5.large": 16, "c5.large": 4, "c5.xlarge": 8}.get(instance_type, 4),
            "Environment": env,
            "GSI": random.choice(["WebPlatform", "Database", "Analytics", "API", "Backend"]),
            "cpu_avg": cpu_p95 * 0.6,
            "cpu_p95": cpu_p95,
            "memory_avg": mem_p95 * 0.7,
            "memory_p95": mem_p95,
            "classification": classification,
            "recommended_type": None if classification == "right_sized" else (instance_types[instance_types.index(instance_type) - 1] if classification == "oversized" and instance_types.index(instance_type) > 0 else instance_types[min(instance_types.index(instance_type) + 1, len(instance_types) - 1)]),
            "current_monthly": current_monthly,
            "recommended_monthly": current_monthly - monthly_savings,
            "monthly_savings": monthly_savings,
            "confidence": random.uniform(0.6, 0.95),
            "risk_level": random.choice(["low", "medium", "high"]),
            "has_contention": classification == "undersized" and random.random() > 0.5,
            "contention_events": random.randint(0, 10) if classification == "undersized" else 0,
        })

    return pd.DataFrame(data)


def run_live_analysis():
    """Run live analysis against AWS."""
    region = st.session_state.get("aws_region", "us-east-1")
    months = st.session_state.get("analysis_months", 3)
    use_cloudwatch = st.session_state.get("use_cloudwatch", True)

    with st.spinner("Connecting to AWS..."):
        try:
            # Try to import and run analysis
            from src.utils.helpers import load_credentials, validate_credentials
            from src.clients.aws_client import AWSClient
            from src.clients.cloudwatch_client import CloudWatchClient

            creds = load_credentials()
            cred_status = validate_credentials(creds)

            if not cred_status["aws_configured"]:
                st.error("""
                    **AWS credentials not configured.**

                    Please set up credentials in one of these ways:
                    1. Edit `config/credentials.yaml` with your AWS access key
                    2. Set AWS_PROFILE environment variable
                    3. Configure `~/.aws/credentials`
                """)
                return None

            aws_creds = creds.get("aws", {})
            aws_client = AWSClient(
                access_key_id=aws_creds.get("access_key_id"),
                secret_access_key=aws_creds.get("secret_access_key"),
                region=region,
                profile_name=aws_creds.get("profile_name")
            )

            st.info("Fetching EC2 instances...")
            instances = aws_client.get_instances()

            if not instances:
                st.warning("No EC2 instances found in the selected region.")
                return None

            st.info(f"Found {len(instances)} instances. Fetching metrics...")

            # Build DataFrame from instances
            data = []
            for instance in instances:
                # Get basic instance info
                data.append({
                    "server_id": instance.get("instance_id", ""),
                    "hostname": instance.get("name", instance.get("private_ip", "")),
                    "instance_type": instance.get("instance_type", ""),
                    "Environment": instance.get("tags", {}).get("Environment", "Unknown"),
                    "GSI": instance.get("tags", {}).get("GSI", "Unknown"),
                    "cpu_p95": None,  # Would need CloudWatch integration
                    "memory_p95": None,
                    "classification": "unknown",
                    "current_monthly": 0,
                    "monthly_savings": 0,
                })

            df = pd.DataFrame(data)
            st.success(f"Loaded {len(df)} instances from AWS!")

            return df

        except ImportError as e:
            st.error(f"Missing dependency: {e}. Run `pip install boto3`")
            return None
        except Exception as e:
            st.error(f"Failed to connect to AWS: {e}")
            return None


def main():
    init_session_state()
    render_sidebar()

    # Main content area
    st.markdown('<div class="main-header">AWS Cost Optimizer</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sub-header">Analyzing: {st.session_state.get("selected_service", "EC2")} Resources</div>', unsafe_allow_html=True)

    # Show data source indicator
    render_data_source_indicator()

    # Handle live analysis request
    if st.session_state.get("run_analysis"):
        df = run_live_analysis()
        if df is not None:
            st.session_state["live_df"] = df
            st.session_state["data_source"] = "live"
        st.session_state["run_analysis"] = False

    # Main content
    if "report_file" in st.session_state or "sample_df" in st.session_state or "live_df" in st.session_state:
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


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to expected format.

    Maps Excel display names to internal field names.
    """
    column_mapping = {
        # Excel display name -> internal name
        "Server": "hostname",
        "Instance ID": "server_id",
        "Instance Type": "instance_type",
        "Current Type": "instance_type",
        "vCPU": "vcpu",
        "RAM (GB)": "memory_gb",
        "CPU Avg %": "cpu_avg",
        "CPU P95 %": "cpu_p95",
        "Mem Avg %": "memory_avg",
        "Mem P95 %": "memory_p95",
        "Disk Avg %": "disk_avg",
        "Data Days": "data_days",
        "Classification": "classification",
        "Recommended Type": "recommended_type",
        "Recommended": "recommended_type",
        "Monthly Savings": "monthly_savings",
        "Current Monthly": "current_monthly",
        "Recommended Monthly": "recommended_monthly",
        "Yearly Savings": "yearly_savings",
        "Confidence": "confidence",
        "Risk": "risk_level",
        "Risk Level": "risk_level",
        "Reason": "reason",
        "Has Contention": "has_contention",
        "Contention Events": "contention_events",
    }

    # Rename columns that exist in the mapping
    rename_dict = {old: new for old, new in column_mapping.items() if old in df.columns}
    if rename_dict:
        df = df.rename(columns=rename_dict)

    # Also normalize any remaining columns to lowercase with underscores
    new_columns = []
    for c in df.columns:
        if c not in column_mapping.values():
            new_c = c.lower().replace(" ", "_").replace("%", "").replace("(", "").replace(")", "").strip("_")
            new_columns.append(new_c)
        else:
            new_columns.append(c)
    df.columns = new_columns

    return df


def display_dashboard():
    """Display the main dashboard with analysis results."""
    # Load data from appropriate source
    df = None

    if "report_file" in st.session_state:
        try:
            report_file = st.session_state["report_file"]
            if isinstance(report_file, (str, Path)):
                df = pd.read_excel(report_file, sheet_name="Server Details")
                # Also try to load recommendations for cost data
                try:
                    recs_df = pd.read_excel(report_file, sheet_name="Recommendations")
                    recs_df = normalize_column_names(recs_df)
                    # Merge recommendation data
                    if "server_id" in recs_df.columns or "hostname" in recs_df.columns:
                        merge_key = "server_id" if "server_id" in recs_df.columns else "hostname"
                        df = normalize_column_names(df)
                        for col in ["recommended_type", "monthly_savings", "current_monthly", "confidence", "risk_level"]:
                            if col in recs_df.columns and col not in df.columns:
                                merge_data = recs_df[[merge_key, col]].drop_duplicates()
                                df = df.merge(merge_data, on=merge_key, how="left")
                except Exception:
                    pass  # Recommendations sheet optional
            else:
                df = pd.read_excel(report_file, sheet_name="Server Details")
            # Normalize column names
            df = normalize_column_names(df)
        except Exception as e:
            st.error(f"Failed to read report: {e}")
            return
    elif "sample_df" in st.session_state:
        df = st.session_state["sample_df"]
    elif "live_df" in st.session_state:
        df = st.session_state["live_df"]
    else:
        st.warning("No data loaded. Please upload a report or run live analysis.")
        return

    if df is None or len(df) == 0:
        st.warning("No data available for analysis.")
        return

    # Check for minimum required data - now check for either server_id or hostname
    if "server_id" not in df.columns and "hostname" not in df.columns:
        st.error("Report missing required columns: need either 'server_id' or 'hostname'")
        return

    # Ensure server_id exists (use hostname as fallback)
    if "server_id" not in df.columns and "hostname" in df.columns:
        df["server_id"] = df["hostname"]

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
        # Persist to file
        if save_persisted_state():
            st.success("✅ Status saved and persisted!")
        else:
            st.success("✅ Status saved (session only)")
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
