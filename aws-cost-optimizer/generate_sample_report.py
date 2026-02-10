#!/usr/bin/env python3
"""Generate a sample report with mock data for testing the dashboard."""

import random
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analysis.rightsizing import RightsizingEngine, SizingClassification
from src.output.report_data import ReportDataBuilder, ServerReport
from src.output.excel_generator import ExcelGenerator

# Mock instance specs
INSTANCE_SPECS = {
    "t3.medium": {"vcpu": 2, "memory_gb": 4, "hourly": 0.0416},
    "t3.large": {"vcpu": 2, "memory_gb": 8, "hourly": 0.0832},
    "t3.xlarge": {"vcpu": 4, "memory_gb": 16, "hourly": 0.1664},
    "m5.large": {"vcpu": 2, "memory_gb": 8, "hourly": 0.096},
    "m5.xlarge": {"vcpu": 4, "memory_gb": 16, "hourly": 0.192},
    "m5.2xlarge": {"vcpu": 8, "memory_gb": 32, "hourly": 0.384},
    "c5.xlarge": {"vcpu": 4, "memory_gb": 8, "hourly": 0.17},
    "c5.2xlarge": {"vcpu": 8, "memory_gb": 16, "hourly": 0.34},
    "c5.4xlarge": {"vcpu": 16, "memory_gb": 32, "hourly": 0.68},
    "r5.xlarge": {"vcpu": 4, "memory_gb": 32, "hourly": 0.252},
    "r5.2xlarge": {"vcpu": 8, "memory_gb": 64, "hourly": 0.504},
    "r5.4xlarge": {"vcpu": 16, "memory_gb": 128, "hourly": 1.008},
    "p3.2xlarge": {"vcpu": 8, "memory_gb": 61, "hourly": 3.06},
}

# Recommended downsizes
DOWNSIZE_MAP = {
    "m5.2xlarge": "m5.xlarge",
    "m5.xlarge": "m5.large",
    "c5.2xlarge": "c5.xlarge",
    "c5.4xlarge": "c5.2xlarge",
    "r5.4xlarge": "r5.2xlarge",
    "r5.2xlarge": "r5.xlarge",
    "t3.xlarge": "t3.large",
    "t3.large": "t3.medium",
}


def generate_mock_metrics(classification: str):
    """Generate mock CPU/memory metrics based on classification."""
    if classification == "oversized":
        cpu_avg = random.uniform(15, 30)
        cpu_p95 = random.uniform(25, 38)
        mem_avg = random.uniform(20, 35)
        mem_p95 = random.uniform(30, 48)
    elif classification == "undersized":
        cpu_avg = random.uniform(70, 85)
        cpu_p95 = random.uniform(82, 95)
        mem_avg = random.uniform(75, 88)
        mem_p95 = random.uniform(85, 96)
    else:  # right_sized
        cpu_avg = random.uniform(40, 55)
        cpu_p95 = random.uniform(50, 68)
        mem_avg = random.uniform(45, 60)
        mem_p95 = random.uniform(55, 73)

    return cpu_avg, cpu_p95, mem_avg, mem_p95


def main():
    # Load sample servers
    csv_path = Path(__file__).parent / "sample_servers.csv"
    df = pd.read_csv(csv_path)

    # Create report builder
    report_builder = ReportDataBuilder()

    # Assign classifications (mix of oversized, right-sized, undersized)
    classifications = (
        ["oversized"] * 10 +      # 40% oversized
        ["right_sized"] * 10 +    # 40% right-sized
        ["undersized"] * 5        # 20% undersized
    )
    random.shuffle(classifications)

    for idx, row in df.iterrows():
        instance_type = row["instance_type"]
        specs = INSTANCE_SPECS.get(instance_type, {"vcpu": 4, "memory_gb": 16, "hourly": 0.2})

        # Assign classification
        classification = classifications[idx % len(classifications)]

        # Generate mock metrics
        cpu_avg, cpu_p95, mem_avg, mem_p95 = generate_mock_metrics(classification)

        # Determine recommendation
        if classification == "oversized":
            recommended_type = DOWNSIZE_MAP.get(instance_type)
            confidence = random.uniform(0.75, 0.95)
            risk_level = "low"
            reason = f"Low utilization (CPU p95: {cpu_p95:.1f}%, Mem p95: {mem_p95:.1f}%)"
        elif classification == "undersized":
            recommended_type = None  # Would need upsize
            confidence = random.uniform(0.6, 0.8)
            risk_level = "high"
            reason = f"High utilization with contention (CPU p95: {cpu_p95:.1f}%, Mem p95: {mem_p95:.1f}%)"
        else:
            recommended_type = None
            confidence = random.uniform(0.8, 0.95)
            risk_level = "low"
            reason = f"Adequate utilization (CPU p95: {cpu_p95:.1f}%, Mem p95: {mem_p95:.1f}%)"

        # Calculate costs
        current_monthly = specs["hourly"] * 730
        if recommended_type and recommended_type in INSTANCE_SPECS:
            recommended_monthly = INSTANCE_SPECS[recommended_type]["hourly"] * 730
            monthly_savings = current_monthly - recommended_monthly
        else:
            recommended_monthly = current_monthly
            monthly_savings = 0

        # Contention for undersized
        has_contention = classification == "undersized"
        contention_events = random.randint(5, 20) if has_contention else 0
        contention_hours = random.uniform(10, 50) if has_contention else 0

        # Build server report
        server_report = ServerReport(
            server_id=row["instance_id"],
            hostname=row["hostname"],
            instance_id=row["instance_id"],
            instance_type=instance_type,
            vcpu=specs["vcpu"],
            memory_gb=specs["memory_gb"],
            region="us-east-1",
            tags={
                "GSI": row["gsi"],
                "Environment": row["environment"],
                "Team": row["team"],
            },
            cpu_avg=cpu_avg,
            cpu_p95=cpu_p95,
            memory_avg=mem_avg,
            memory_p95=mem_p95,
            disk_avg=random.uniform(30, 60),
            disk_p95=random.uniform(40, 70),
            data_days=90,
            has_contention=has_contention,
            contention_events=contention_events,
            contention_hours=contention_hours,
            classification=classification,
            recommended_type=recommended_type,
            confidence=confidence,
            risk_level=risk_level,
            reason=reason,
            current_monthly=current_monthly,
            recommended_monthly=recommended_monthly,
            monthly_savings=monthly_savings,
            yearly_savings=monthly_savings * 12,
        )

        report_builder.add_server(server_report)

    # Generate Excel report
    output_path = Path(__file__).parent / "sample_report.xlsx"
    generator = ExcelGenerator(output_path)
    generator.generate(report_builder)

    # Print summary
    summary = report_builder.build_summary()
    print("\n" + "=" * 60)
    print("SAMPLE REPORT GENERATED")
    print("=" * 60)
    print(f"Servers Analyzed:      {summary['total_servers']}")
    print(f"Current Monthly Spend: ${summary['total_current_monthly']:,.2f}")
    print(f"Potential Savings:     ${summary['total_monthly_savings']:,.2f}/month")
    print(f"                       ${summary['total_yearly_savings']:,.2f}/year")
    print("-" * 60)
    print(f"Oversized (downsize):  {summary['oversized_count']}")
    print(f"Right-sized:           {summary['right_sized_count']}")
    print(f"Undersized (upsize):   {summary['undersized_count']}")
    print(f"With Contention:       {summary['contention_count']}")
    print("=" * 60)
    print(f"\nReport saved to: {output_path}")
    print(f"\nOpen the dashboard and upload this file to see the visualizations!")


if __name__ == "__main__":
    main()
