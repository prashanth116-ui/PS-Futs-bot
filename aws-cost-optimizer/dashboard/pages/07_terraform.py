"""Terraform Output Generator page."""

import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Terraform Generator", page_icon="🏗️", layout="wide")

st.title("Terraform Output Generator")
st.caption("Generate Infrastructure as Code to implement rightsizing recommendations")


def load_data():
    """Load data from session state."""
    if "report_file" in st.session_state:
        return pd.read_excel(st.session_state["report_file"], sheet_name="Server Details")
    return None


df = load_data()

if df is None:
    st.info("Please upload a report from the main page to generate Terraform code.")
    st.stop()

# Filter to servers with recommendations
if "recommended_type" not in df.columns:
    st.warning("No recommendation data available")
    st.stop()

recs_df = df[df["recommended_type"].notna()].copy()

if len(recs_df) == 0:
    st.info("No rightsizing recommendations to generate Terraform for.")
    st.stop()

# Configuration
st.header("Configuration")

col1, col2 = st.columns(2)

with col1:
    output_format = st.selectbox(
        "Output Format",
        ["Terraform (HCL)", "AWS CLI Commands", "CloudFormation (YAML)"]
    )

    include_backup = st.checkbox("Include AMI backup before resize", value=True)
    include_tags = st.checkbox("Preserve existing tags", value=True)

with col2:
    # Server selection
    st.markdown("### Select Servers")

    risk_filter = st.multiselect(
        "Filter by risk level:",
        options=recs_df["risk_level"].dropna().unique().tolist() if "risk_level" in recs_df.columns else [],
        default=["low"] if "low" in recs_df["risk_level"].values else []
    )

    if risk_filter and "risk_level" in recs_df.columns:
        recs_df = recs_df[recs_df["risk_level"].isin(risk_filter)]

    selected_servers = st.multiselect(
        "Select servers:",
        options=recs_df["hostname"].tolist() if "hostname" in recs_df.columns else [],
        default=recs_df["hostname"].tolist()[:10] if "hostname" in recs_df.columns else []
    )

if not selected_servers:
    st.warning("Please select at least one server.")
    st.stop()

selected_df = recs_df[recs_df["hostname"].isin(selected_servers)]

st.divider()

# Generate output
st.header("Generated Code")


def generate_terraform(servers_df, include_backup=True, include_tags=True):
    """Generate Terraform HCL code."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    tf_code = f'''# AWS Cost Optimization - Instance Rightsizing
# Generated: {timestamp}
# Servers: {len(servers_df)}

# WARNING: Review carefully before applying!
# This will modify instance types which requires instance stop/start.

terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "us-east-1"  # Update with your region
}}

# Data sources to get current instance info
'''

    for idx, row in servers_df.iterrows():
        instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))
        hostname = row.get("hostname", instance_id)
        current_type = row.get("instance_type", "unknown")
        recommended_type = row.get("recommended_type", "unknown")

        safe_name = hostname.replace("-", "_").replace(".", "_")

        tf_code += f'''
# {hostname}: {current_type} -> {recommended_type}
data "aws_instance" "{safe_name}" {{
  instance_id = "{instance_id}"
}}

'''

    if include_backup:
        tf_code += '''
# AMI Backups (create before resizing)
'''
        for idx, row in servers_df.iterrows():
            hostname = row.get("hostname", f"server-{idx}")
            instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))
            safe_name = hostname.replace("-", "_").replace(".", "_")

            tf_code += f'''
resource "aws_ami_from_instance" "backup_{safe_name}" {{
  name               = "{hostname}-backup-${{formatdate("YYYY-MM-DD", timestamp())}}"
  source_instance_id = "{instance_id}"

  tags = {{
    Name        = "{hostname}-backup"
    Purpose     = "Pre-rightsizing backup"
    OriginalType = data.aws_instance.{safe_name}.instance_type
    CreatedBy   = "cost-optimizer"
  }}
}}
'''

    tf_code += '''
# Instance Type Modifications
# Note: Instances must be stopped to change type
'''

    for idx, row in servers_df.iterrows():
        hostname = row.get("hostname", f"server-{idx}")
        instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))
        recommended_type = row.get("recommended_type", "unknown")
        safe_name = hostname.replace("-", "_").replace(".", "_")

        tf_code += f'''
# Resize {hostname} to {recommended_type}
resource "null_resource" "resize_{safe_name}" {{
  triggers = {{
    instance_id = "{instance_id}"
    new_type    = "{recommended_type}"
  }}

  provisioner "local-exec" {{
    command = <<-EOT
      # Stop instance
      aws ec2 stop-instances --instance-ids {instance_id}
      aws ec2 wait instance-stopped --instance-ids {instance_id}

      # Modify instance type
      aws ec2 modify-instance-attribute --instance-id {instance_id} --instance-type "{recommended_type}"

      # Start instance
      aws ec2 start-instances --instance-ids {instance_id}
      aws ec2 wait instance-running --instance-ids {instance_id}

      echo "Resized {hostname} to {recommended_type}"
    EOT
  }}

  depends_on = [aws_ami_from_instance.backup_{safe_name}]
}}
'''

    tf_code += f'''
# Output summary
output "rightsizing_summary" {{
  value = {{
    total_instances = {len(servers_df)}
    changes = [
'''

    for idx, row in servers_df.iterrows():
        hostname = row.get("hostname", f"server-{idx}")
        current_type = row.get("instance_type", "unknown")
        recommended_type = row.get("recommended_type", "unknown")
        savings = row.get("monthly_savings", 0)
        tf_code += f'''      "{hostname}: {current_type} -> {recommended_type} (${savings:.2f}/mo)",
'''

    tf_code += '''    ]
  }
}
'''

    return tf_code


def generate_aws_cli(servers_df, include_backup=True):
    """Generate AWS CLI commands."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    cli_code = f'''#!/bin/bash
# AWS Cost Optimization - Instance Rightsizing
# Generated: {timestamp}
# Servers: {len(servers_df)}

# WARNING: Review carefully before running!
# This will modify instance types which requires instance stop/start.

set -e  # Exit on error

'''

    if include_backup:
        cli_code += '''# Step 1: Create AMI backups
echo "Creating AMI backups..."

'''
        for idx, row in servers_df.iterrows():
            hostname = row.get("hostname", f"server-{idx}")
            instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))

            cli_code += f'''# Backup {hostname}
aws ec2 create-image \\
  --instance-id {instance_id} \\
  --name "{hostname}-backup-$(date +%Y-%m-%d)" \\
  --description "Pre-rightsizing backup" \\
  --no-reboot

'''

    cli_code += '''# Step 2: Resize instances
echo "Resizing instances..."

'''

    for idx, row in servers_df.iterrows():
        hostname = row.get("hostname", f"server-{idx}")
        instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))
        current_type = row.get("instance_type", "unknown")
        recommended_type = row.get("recommended_type", "unknown")
        savings = row.get("monthly_savings", 0)

        cli_code += f'''# {hostname}: {current_type} -> {recommended_type} (saves ${savings:.2f}/month)
echo "Resizing {hostname}..."
aws ec2 stop-instances --instance-ids {instance_id}
aws ec2 wait instance-stopped --instance-ids {instance_id}
aws ec2 modify-instance-attribute --instance-id {instance_id} --instance-type "{recommended_type}"
aws ec2 start-instances --instance-ids {instance_id}
aws ec2 wait instance-running --instance-ids {instance_id}
echo "{hostname} resized successfully"

'''

    cli_code += '''echo "All instances resized successfully!"
'''

    return cli_code


def generate_cloudformation(servers_df):
    """Generate CloudFormation YAML."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    cf_code = f'''# AWS Cost Optimization - Instance Rightsizing
# Generated: {timestamp}
# Note: CloudFormation cannot directly modify existing instances.
# This template documents the target state.

AWSTemplateFormatVersion: '2010-09-09'
Description: 'Rightsizing recommendations - target instance types'

# This is a documentation template showing target configurations.
# Use AWS CLI or Terraform to actually modify existing instances.

Metadata:
  RightsizingRecommendations:
    GeneratedAt: "{timestamp}"
    TotalServers: {len(servers_df)}
    Recommendations:
'''

    for idx, row in servers_df.iterrows():
        hostname = row.get("hostname", f"server-{idx}")
        instance_id = row.get("instance_id", row.get("server_id", f"unknown-{idx}"))
        current_type = row.get("instance_type", "unknown")
        recommended_type = row.get("recommended_type", "unknown")
        savings = row.get("monthly_savings", 0)

        cf_code += f'''      - Hostname: "{hostname}"
        InstanceId: "{instance_id}"
        CurrentType: "{current_type}"
        RecommendedType: "{recommended_type}"
        MonthlySavings: {savings:.2f}
'''

    return cf_code


# Generate the code
if output_format == "Terraform (HCL)":
    code = generate_terraform(selected_df, include_backup, include_tags)
    file_ext = "tf"
    lang = "hcl"
elif output_format == "AWS CLI Commands":
    code = generate_aws_cli(selected_df, include_backup)
    file_ext = "sh"
    lang = "bash"
else:
    code = generate_cloudformation(selected_df)
    file_ext = "yaml"
    lang = "yaml"

# Display code
st.code(code, language=lang, line_numbers=True)

# Download button
st.download_button(
    label=f"Download {output_format}",
    data=code,
    file_name=f"rightsizing_{datetime.now().strftime('%Y%m%d')}.{file_ext}",
    mime="text/plain"
)

st.divider()

# Summary
st.header("Implementation Summary")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Servers to Modify", len(selected_df))

with col2:
    total_savings = selected_df["monthly_savings"].sum()
    st.metric("Monthly Savings", f"${total_savings:,.2f}")

with col3:
    st.metric("Yearly Savings", f"${total_savings * 12:,.2f}")

# Warnings
st.warning("""
**Before applying these changes:**
1. Review each change carefully
2. Ensure you have recent backups
3. Schedule during maintenance windows
4. Have a rollback plan ready
5. Monitor instances after resizing
""")
