# AWS Cost Optimizer

A Python-based tool for analyzing AWS EC2 resource usage and generating rightsizing recommendations with projected cost savings.

## Features

- **Multi-Source Data Collection**: Integrates with Dynatrace, AWS CloudWatch, and AWS Cost Explorer
- **Comprehensive Analysis**: Calculates CPU, memory, and disk usage statistics (avg, p95, etc.)
- **Contention Detection**: Identifies resource bottlenecks and contention events
- **Rightsizing Recommendations**: Generates instance type recommendations with confidence scores
- **Cost Projections**: Calculates potential monthly and yearly savings
- **Excel Reports**: Detailed multi-sheet reports with charts and summaries
- **Interactive Dashboard**: Streamlit-based web dashboard for exploration

## Installation

```bash
cd aws-cost-optimizer
pip install -r requirements.txt
```

## Configuration

1. Copy the credentials template:
   ```bash
   cp config/credentials.template.yaml config/credentials.yaml
   ```

2. Edit `config/credentials.yaml` with your API credentials:

   **Dynatrace:**
   - Get API token from: Settings → Integration → Dynatrace API → Generate token
   - Required scopes: `metrics.read`, `entities.read`, `problems.read`

   **AWS:**
   - Create IAM user with permissions:
     - `ec2:DescribeInstances`
     - `ec2:DescribeInstanceTypes`
     - `ce:GetCostAndUsage`
     - `pricing:GetProducts`
     - `cloudwatch:GetMetricStatistics` (optional)

## Usage

### Generate Report from CSV Input

```bash
python run.py --input servers.csv --output report.xlsx
```

### Generate Report from AWS Tags

```bash
# Single tag
python run.py --tag GSI MyProject --output report.xlsx

# Multiple tags
python run.py --tag Environment Production --tag Team Platform --output report.xlsx
```

### Launch Interactive Dashboard

```bash
python run.py --dashboard
```

### Additional Options

```bash
# Specify analysis period (default: 3 months)
python run.py --input servers.csv --months 6 --output report.xlsx

# Use CloudWatch instead of Dynatrace
python run.py --input servers.csv --use-cloudwatch --output report.xlsx

# Test connections only (dry run)
python run.py --dry-run

# Verbose logging
python run.py --input servers.csv --verbose
```

## Input File Format

The CSV/Excel input file should contain server information. The tool auto-detects common column names:

| Column | Alternatives |
|--------|-------------|
| hostname | host, server, server_name, name |
| instance_id | instanceid, instance, ec2_instance |
| ip_address | ip, private_ip |
| gsi | cost_center, project, application |
| environment | env, stage |
| instance_type | type, size |

Example:
```csv
hostname,instance_id,instance_type,gsi,environment
web-server-1,i-12345abc,m5.xlarge,WebApp,Production
db-server-1,i-67890def,r5.2xlarge,Database,Production
```

## Output

### Excel Report Sheets

1. **Executive Summary**: Key metrics, classification breakdown, top savings opportunities
2. **Server Details**: Complete server list with utilization metrics
3. **Recommendations**: Rightsizing recommendations with risk levels
4. **Cost Analysis**: Current vs. optimized spending, savings by GSI
5. **Contention Report**: Servers with resource contention issues

### Rightsizing Classifications

| Classification | Criteria | Action |
|---------------|----------|--------|
| **Oversized** | CPU p95 < 40% AND Memory p95 < 50% | Safe to downsize |
| **Right-sized** | CPU p95 40-70% OR Memory p95 50-75% | No change needed |
| **Undersized** | CPU p95 > 80% OR Memory p95 > 85% OR contention | Consider upgrade |

## Dashboard

Launch the Streamlit dashboard for interactive analysis:

```bash
streamlit run dashboard/app.py
```

Features:
- Upload existing Excel reports
- Filter by classification, instance type, GSI
- Interactive charts and visualizations
- Drill-down to individual server details
- Export filtered data

## Project Structure

```
aws-cost-optimizer/
├── config/
│   ├── config.yaml              # Main configuration
│   ├── credentials.template.yaml # API credentials template
│   └── instance_types.yaml      # AWS instance catalog
├── src/
│   ├── clients/                 # API clients
│   ├── input/                   # Input handlers
│   ├── analysis/                # Analysis engines
│   ├── cost/                    # Cost calculations
│   ├── output/                  # Report generation
│   └── utils/                   # Utilities
├── dashboard/                   # Streamlit dashboard
├── tests/                       # Unit tests
├── run.py                       # CLI entry point
└── requirements.txt
```

## Running Tests

```bash
pytest tests/ -v
```

## License

MIT License
