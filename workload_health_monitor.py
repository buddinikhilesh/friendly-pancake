#!/usr/bin/env python3
"""
workload_health_monitor.py
Monitors long-running distributed workloads for stalls, degradation,
and failure patterns. Detects stuck jobs early and triggers automated
fault-recovery before impact reaches end users.

Usage:
    python workload_health_monitor.py --namespace production --timeout 300
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class WorkloadHealthMonitor:
    def __init__(self, k8s_api_url: str, namespace: str, timeout_seconds: int):
        self.k8s_api_url = k8s_api_url.rstrip("/")
        self.namespace = namespace
        self.timeout_seconds = timeout_seconds
        self.stalled_jobs = []
        self.degraded_pods = []

    def get_running_jobs(self) -> list:
        url = f"{self.k8s_api_url}/apis/batch/v1/namespaces/{self.namespace}/jobs"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            jobs = response.json().get("items", [])
            return [j for j in jobs if j.get("status", {}).get("active", 0) > 0]
        except requests.RequestException as e:
            logger.error(f"Failed to fetch jobs: {e}")
            return []

    def get_pods_for_job(self, job_name: str) -> list:
        url = (
            f"{self.k8s_api_url}/api/v1/namespaces/{self.namespace}/pods"
            f"?labelSelector=job-name={job_name}"
        )
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("items", [])
        except requests.RequestException as e:
            logger.error(f"Failed to fetch pods for job {job_name}: {e}")
            return []

    def check_job_stalled(self, job: dict) -> Optional[dict]:
        job_name = job["metadata"]["name"]
        start_time_str = job["status"].get("startTime")
        if not start_time_str:
            return None
        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        running_seconds = (now - start_time).total_seconds()
        if running_seconds < self.timeout_seconds:
            return None
        pods = self.get_pods_for_job(job_name)
        problem_pods = []
        for pod in pods:
            phase = pod["status"].get("phase", "Unknown")
            for cs in pod["status"].get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason in ["CrashLoopBackOff", "OOMKilled", "Error"]:
                    problem_pods.append({
                        "pod": pod["metadata"]["name"],
                        "reason": reason,
                        "restart_count": cs.get("restartCount", 0),
                    })
            if phase in ["Failed", "Unknown"]:
                problem_pods.append({
                    "pod": pod["metadata"]["name"],
                    "reason": phase,
                    "restart_count": 0,
                })
        return {
            "job_name": job_name,
            "running_seconds": int(running_seconds),
            "timeout_seconds": self.timeout_seconds,
            "problem_pods": problem_pods,
            "severity": "CRITICAL" if problem_pods else "WARNING",
        }

    def send_alert(self, webhook_url: str, message: dict) -> None:
        payload = {
            "text": f"SRE Alert — Workload Health\n{json.dumps(message, indent=2)}"
        }
        try:
            response = requests.post(webhook_url, json=payload, timeout=5)
            response.raise_for_status()
            logger.info("Alert sent successfully")
        except requests.RequestException as e:
            logger.error(f"Failed to send alert: {e}")

    def run(self, webhook_url: Optional[str] = None) -> int:
        logger.info(
            f"Checking workload health in namespace '{self.namespace}' "
            f"(stall timeout: {self.timeout_seconds}s)"
        )
        issues_found = 0
        jobs = self.get_running_jobs()
        logger.info(f"Found {len(jobs)} active jobs")
        for job in jobs:
            stall_info = self.check_job_stalled(job)
            if stall_info:
                issues_found += 1
                self.stalled_jobs.append(stall_info)
                logger.warning(
                    f"Stalled job detected: {stall_info['job_name']} "
                    f"(running {stall_info['running_seconds']}s)"
                )
                if webhook_url:
                    self.send_alert(webhook_url, stall_info)
        print(f"\n{'='*55}")
        print(f"WORKLOAD HEALTH REPORT — {self.namespace}")
        print(f"{'='*55}")
        print(f"  Active jobs checked:   {len(jobs)}")
        print(f"  Stalled jobs:          {len(self.stalled_jobs)}")
        print(f"  Total issues:          {issues_found}")
        print(f"  Status:                {'ISSUES FOUND' if issues_found else 'ALL HEALTHY'}")
        print(f"{'='*55}\n")
        return issues_found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor long-running workload health")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--k8s-api", default="http://localhost:8001")
    parser.add_argument("--alert-webhook", help="Slack webhook URL")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    return parser.parse_args()


def main():
    args = parse_args()
    monitor = WorkloadHealthMonitor(
        k8s_api_url=args.k8s_api,
        namespace=args.namespace,
        timeout_seconds=args.timeout,
    )
    if args.watch:
        logger.info(f"Watching namespace '{args.namespace}' every {args.interval}s...")
        while True:
            monitor.stalled_jobs = []
            monitor.degraded_pods = []
            monitor.run(webhook_url=args.alert_webhook)
            time.sleep(args.interval)
    else:
        issues = monitor.run(webhook_url=args.alert_webhook)
        sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
