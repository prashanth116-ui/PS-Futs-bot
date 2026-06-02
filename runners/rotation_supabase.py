"""Push rotation scan results to Supabase for the ew-scanner web dashboard."""

import logging
import os
from datetime import date

from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(__file__), "..", "config", ".env")
load_dotenv(_env_path)

log = logging.getLogger("rotation_scanner")


def push_to_supabase(scan_data: dict) -> bool:
    """Upsert scan results into the rotation_scan_results table.

    Args:
        scan_data: Full result dict from run_scan(return_full=True).
            Expected keys: all_sectors, passed_stocks, rejected_stocks,
            sectors_analyzed, interesting_sectors, stocks_passed, etc.

    Returns:
        True on success, False on failure.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        log.warning("SUPABASE_URL / SUPABASE_KEY not set — skipping push")
        return False

    try:
        from supabase import create_client

        client = create_client(url, key)

        scan_date = date.today().isoformat()

        row = {
            "scan_date": scan_date,
            "sectors_data": _sanitize(scan_data.get("all_sectors", [])),
            "passed_stocks": _sanitize(scan_data.get("passed_stocks", [])),
            "rejected_stocks": _sanitize(scan_data.get("rejected_stocks", [])),
            "summary": {
                "sectors_analyzed": scan_data.get("sectors_analyzed", 0),
                "interesting_sectors": scan_data.get("interesting_sectors", 0),
                "stocks_enriched": scan_data.get("stocks_enriched", 0),
                "stocks_passed": scan_data.get("stocks_passed", 0),
                "alerts_sent": scan_data.get("alerts_sent", 0),
                "scan_date": scan_data.get("scan_date", scan_date),
            },
        }

        result = client.table("rotation_scan_results").upsert(
            row, on_conflict="scan_date"
        ).execute()

        log.info("Supabase push OK — scan_date=%s, rows=%d",
                 scan_date, len(result.data) if result.data else 0)
        return True

    except Exception as e:
        log.error("Supabase push failed: %s", e)
        return False


def _sanitize(obj):
    """Convert numpy/pandas types to JSON-serializable Python types."""
    import numpy as np

    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj
