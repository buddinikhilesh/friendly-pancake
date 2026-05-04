#!/usr/bin/env python3
"""
slo_tracker.py
Tracks SLO/SLI error budget burn rate for distributed services.
Queries Prometheus for availability metrics and calculates remaining
error budget, burn rate, and projected exhaustion time.

Usage:
    python slo_tracker.py --service payment-api --window 30d --slo 99.9
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional
import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class SLOTracker:
    def __init__(self, prometheus_url: str, slo_target: float):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.slo_target = slo_target
        self.error_budget_total = 1.0 - (slo_target / 100.0)

    def query_prometheus(self, query: str, start: datetime, end: datetime) -> list:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": "60s",
        }
        try:
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data["status"] != "success":
                logger.error(f"Prometheus query failed: {data}")
                return []
            return data["data"]["result"]
        except requests.RequestException as e:
            logger.error(f"Failed to query Prometheus: {e}")
            return []

    def calculate_availability(self, service: str, window_days: int) -> Optional[float]:
        end = datetime.utcnow()
        start = end - timedelta(days=window_days)
        total_query = f'sum(increase(http_requests_total{{service="{service}"}}[{window_days}d]))'
        error_query = f'sum(increase(http_requests_total{{service="{service}",status=~"5.."}}[{window_days}d]))'
        total_results = self.query_prometheus(total_query, start, end)
        error_results = self.query_prometheus(error_query, start, end)
        if not total_results or not error_results:
            logger.warning(f"No data for service {service}")
            return None
        total = float(total_results[0]["values"][-1][1])
        errors = float(error_results[0]["values"][-1][1])
        if total == 0:
            return None
        return (total - errors) / total * 100

    def calculate_error_budget(self, service: str, window_days: int) -> dict:
        availability = self.calculate_availability(service, window_days)
        if availability is None:
            return {"error": f"No availability data for {service}"}
        actual_error_rate = 1.0 - (availability / 100.0)
        allowed_error_rate = self.error_budget_total
        remaining_budget_pct = max(
            0, (allowed_error_rate - actual_error_rate) / allowed_error_rate * 100
        )
        burn_rate = actual_error_rate / allowed_error_rate
        days_remaining = (
            (remaining_budget_pct / 100) * window_days / burn_rate
            if burn_rate > 0 else float("inf")
        )
        return {
            "service": service,
            "slo_target": self.slo_target,
            "current_availability": round(availability, 4),
            "error_budget_remaining_pct": round(remaining_budget_pct, 2),
            "burn_rate": round(burn_rate, 3),
            "days_until_exhaustion": round(days_remaining, 1) if days_remaining != float("inf") else "inf",
            "status": "CRITICAL" if remaining_budget_pct < 10 else
                      "WARNING" if remaining_budget_pct < 30 else "OK",
        }

    def report(self, service: str, window_days: int) -> None:
        result = self.calculate_error_budget(service, window_days)
        if "error" in result:
            logger.error(result["error"])
            return
        status_icon = {"OK": "OK", "WARNING": "WARNING", "CRITICAL": "CRITICAL"}.get(result["status"], "")
        print(f"\n{'='*55}")
        print(f"SLO REPORT — {result['service']}")
        print(f"{'='*55}")
        print(f"  SLO Target:              {result['slo_target']}%")
        print(f"  Current Availability:    {result['current_availability']}%")
        print(f"  Error Budget Remaining:  {result['error_budget_remaining_pct']}%")
        print(f"  Burn Rate:               {result['burn_rate']}x")
        print(f"  Days Until Exhaustion:   {result['days_until_exhaustion']}")
        print(f"  Status:                  {status_icon} {result['status']}")
        print(f"{'='*55}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track SLO/SLI error budget burn rate")
    parser.add_argument("--service", help="Service name to track")
    parser.add_argument("--window", default="30d", help="Lookback window e.g. 30d")
    parser.add_argument("--slo", type=float, default=99.9, help="SLO target percentage")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    return parser.parse_args()


def main():
    args = parse_args()
    window_days = int(args.window.replace("d", ""))
    tracker = SLOTracker(prometheus_url=args.prometheus_url, slo_target=args.slo)
    if args.service:
        tracker.report(args.service, window_days)
    else:
        logger.error("Provide --service")
        sys.exit(1)


if __name__ == "__main__":
    main()
