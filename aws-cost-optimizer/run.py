#!/usr/bin/env python3
"""CLI entry point for AWS Cost Optimizer."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.helpers import load_config, load_credentials, setup_logging
from src.clients.aws_client import AWSClient
from src.clients.dynatrace_client import DynatraceClient
from src.clients.cloudwatch_client import CloudWatchClient
from src.input.csv_parser import CSVParser
from src.input.tag_query import TagQuery
from src.analysis.metrics_analyzer import MetricsAnalyzer
from src.analysis.contention_detector import ContentionDetector
from src.analysis.rightsizing import RightsizingEngine
from src.cost.current_spend import CurrentSpendCalculator
from src.cost.projections import SavingsProjector
from src.output.report_data import ReportDataBuilder
from src.output.excel_generator import ExcelGenerator


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="AWS Cost Optimization Tool - Analyze EC2 usage and generate rightsizing recommendations"
    )

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--input", "-i",
        type=str,
        help="Path to CSV/Excel file with server list"
    )
    input_group.add_argument(
        "--tag", "-t",
        action="append",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Query AWS by tag (can be specified multiple times)"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=f"cost_optimization_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
        help="Output Excel file path (default: cost_optimization_report_YYYYMMDD.xlsx)"
    )

    parser.add_argument(
        "--months", "-m",
        type=int,
        default=3,
        help="Number of months of historical data to analyze (default: 3)"
    )

    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the Streamlit dashboard instead of generating a report"
    )

    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region (default: us-east-1)"
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to custom config file"
    )

    parser.add_argument(
        "--credentials",
        type=str,
        help="Path to credentials file"
    )

    parser.add_argument(
        "--use-cloudwatch",
        action="store_true",
        help="Use CloudWatch for metrics instead of Dynatrace"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test connections without generating report"
    )

    return parser.parse_args()


def get_instances(
    args,
    aws_client: AWSClient,
    csv_parser: Optional[CSVParser] = None
) -> List[Dict]:
    """Get list of instances to analyze.

    Args:
        args: Command line arguments
        aws_client: AWS client instance
        csv_parser: Optional CSV parser for file input

    Returns:
        List of instance dictionaries
    """
    if args.input:
        # Parse from CSV/Excel file
        parser = CSVParser(args.input)
        servers = parser.parse()

        # Enrich with AWS data
        instance_ids = [s.get("instance_id") for s in servers if s.get("instance_id")]
        if instance_ids:
            aws_instances = aws_client.get_instances(instance_ids=instance_ids)
            aws_map = {i["instance_id"]: i for i in aws_instances}

            for server in servers:
                if server.get("instance_id") in aws_map:
                    server.update(aws_map[server["instance_id"]])

        return servers

    elif args.tag:
        # Query AWS by tags
        tags = {key: value for key, value in args.tag}
        tag_query = TagQuery(aws_client)
        return tag_query.query(tags=tags)

    else:
        # Get all running instances
        return aws_client.get_instances()


def get_metrics(
    instances: List[Dict],
    args,
    dynatrace_client: Optional[DynatraceClient] = None,
    cloudwatch_client: Optional[CloudWatchClient] = None
) -> Dict[str, Dict]:
    """Get metrics for all instances.

    Args:
        instances: List of instance dictionaries
        args: Command line arguments
        dynatrace_client: Dynatrace client
        cloudwatch_client: CloudWatch client

    Returns:
        Dictionary mapping instance_id to metrics data
    """
    metrics_data = {}

    for instance in instances:
        instance_id = instance.get("instance_id")
        if not instance_id:
            continue

        if args.use_cloudwatch and cloudwatch_client:
            # Use CloudWatch
            metrics = cloudwatch_client.get_instance_metrics(
                instance_id=instance_id,
                months=args.months
            )
        elif dynatrace_client:
            # Use Dynatrace - need to find host by IP or hostname
            hostname = instance.get("name") or instance.get("private_ip")
            if hostname:
                host = dynatrace_client.get_host_by_name(hostname)
                if host:
                    metrics = dynatrace_client.get_host_metrics(
                        host_id=host["entityId"],
                        months=args.months
                    )
                else:
                    metrics = {}
            else:
                metrics = {}
        else:
            # Fallback to CloudWatch if available
            if cloudwatch_client:
                metrics = cloudwatch_client.get_instance_metrics(
                    instance_id=instance_id,
                    months=args.months
                )
            else:
                metrics = {}

        metrics_data[instance_id] = metrics

    return metrics_data


def run_analysis(args):
    """Run the cost optimization analysis.

    Args:
        args: Command line arguments
    """
    logger = setup_logging("DEBUG" if args.verbose else "INFO")
    logger.info("Starting AWS Cost Optimization analysis")

    # Load configuration
    try:
        config = load_config(args.config)
        credentials = load_credentials(args.credentials)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    # Initialize clients
    aws_creds = credentials.get("aws", {})
    aws_client = AWSClient(
        access_key_id=aws_creds.get("access_key_id"),
        secret_access_key=aws_creds.get("secret_access_key"),
        region=args.region,
        profile_name=aws_creds.get("profile_name")
    )

    dynatrace_client = None
    cloudwatch_client = None

    if args.use_cloudwatch:
        cloudwatch_client = CloudWatchClient(
            access_key_id=aws_creds.get("access_key_id"),
            secret_access_key=aws_creds.get("secret_access_key"),
            region=args.region,
            profile_name=aws_creds.get("profile_name")
        )
    else:
        dt_creds = credentials.get("dynatrace", {})
        if dt_creds.get("environment_url") and dt_creds.get("api_token"):
            dynatrace_client = DynatraceClient(
                environment_url=dt_creds["environment_url"],
                api_token=dt_creds["api_token"]
            )

    # Test connections
    if args.dry_run:
        logger.info("Testing connections...")
        aws_ok = aws_client.test_connection()
        logger.info(f"AWS connection: {'OK' if aws_ok else 'FAILED'}")

        if dynatrace_client:
            dt_ok = dynatrace_client.test_connection()
            logger.info(f"Dynatrace connection: {'OK' if dt_ok else 'FAILED'}")

        if cloudwatch_client:
            cw_ok = cloudwatch_client.test_connection()
            logger.info(f"CloudWatch connection: {'OK' if cw_ok else 'FAILED'}")

        return

    # Get instances
    logger.info("Retrieving instances...")
    instances = get_instances(args, aws_client)
    logger.info(f"Found {len(instances)} instances to analyze")

    if not instances:
        logger.warning("No instances found. Check your input or tag filters.")
        sys.exit(0)

    # Get metrics
    logger.info("Retrieving metrics...")
    metrics_data = get_metrics(
        instances, args,
        dynatrace_client=dynatrace_client,
        cloudwatch_client=cloudwatch_client
    )

    # Initialize analyzers
    metrics_analyzer = MetricsAnalyzer(config.get("analysis", {}))
    contention_detector = ContentionDetector()
    rightsizing_engine = RightsizingEngine()
    spend_calculator = CurrentSpendCalculator(aws_client, region=args.region)
    savings_projector = SavingsProjector(spend_calculator)

    # Build report
    logger.info("Analyzing data...")
    report_builder = ReportDataBuilder()

    for instance in instances:
        instance_id = instance.get("instance_id")
        if not instance_id:
            continue

        # Get instance type info
        instance_type = instance.get("instance_type")
        if instance_type:
            instance_specs = aws_client.get_instance_type_info(instance_type)
        else:
            instance_specs = {}

        # Analyze metrics
        server_metrics = metrics_analyzer.analyze_server(
            server_id=instance_id,
            metrics_data=metrics_data.get(instance_id, {}),
            hostname=instance.get("name")
        )

        # Detect contention
        contention = contention_detector.analyze_server(
            server_id=instance_id,
            metrics_data=metrics_data.get(instance_id, {})
        )

        # Generate recommendation
        cpu_p95 = server_metrics.cpu.p95 if server_metrics.cpu else None
        memory_p95 = server_metrics.memory.p95 if server_metrics.memory else None

        recommendation = rightsizing_engine.recommend(
            server_id=instance_id,
            current_instance_type=instance_type or "",
            cpu_p95=cpu_p95,
            memory_p95=memory_p95,
            has_contention=contention.has_contention,
            hostname=instance.get("name"),
            instance_specs=instance_specs
        )

        # Project savings
        projection = savings_projector.project_savings(recommendation)

        # Build server report
        server_report = report_builder.build_server_report(
            instance=instance,
            metrics=server_metrics,
            contention=contention,
            recommendation=recommendation,
            projection=projection
        )
        report_builder.add_server(server_report)

    # Generate Excel report
    logger.info(f"Generating report: {args.output}")
    generator = ExcelGenerator(args.output)
    output_path = generator.generate(report_builder)

    # Print summary
    summary = report_builder.build_summary()
    print("\n" + "=" * 60)
    print("AWS COST OPTIMIZATION SUMMARY")
    print("=" * 60)
    print(f"Servers Analyzed:      {summary['total_servers']}")
    print(f"Current Monthly Spend: ${summary['total_current_monthly']:,.2f}")
    print(f"Potential Savings:     ${summary['total_monthly_savings']:,.2f}/month")
    print(f"                       ${summary['total_yearly_savings']:,.2f}/year")
    print(f"Savings Percentage:    {summary['savings_percentage']:.1f}%")
    print("-" * 60)
    print(f"Oversized (downsize):  {summary['oversized_count']}")
    print(f"Right-sized:           {summary['right_sized_count']}")
    print(f"Undersized (upsize):   {summary['undersized_count']}")
    print(f"With Contention:       {summary['contention_count']}")
    print("=" * 60)
    print(f"\nReport saved to: {output_path}")


def launch_dashboard():
    """Launch the Streamlit dashboard."""
    import subprocess
    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"

    if not dashboard_path.exists():
        print(f"Dashboard not found: {dashboard_path}")
        sys.exit(1)

    subprocess.run(["streamlit", "run", str(dashboard_path)])


def main():
    """Main entry point."""
    args = parse_args()

    if args.dashboard:
        launch_dashboard()
    else:
        run_analysis(args)


if __name__ == "__main__":
    main()
