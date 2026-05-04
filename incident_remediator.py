#!/usr/bin/env python3
"""
incident_remediator.py
Auto-remediates known recurring incidents using runbook automation.
Reads runbook YAML files and executes remediation steps automatically
when incident patterns are detected — eliminating manual toil.

Usage:
    python incident_remediator.py --runbook runbooks/high-memory.yaml --dry-run
"""

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class IncidentRemediator:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.remediated = []
        self.failed = []
        if dry_run:
            logger.info("DRY RUN mode — no changes will be made")

    def load_runbook(self, runbook_path: str) -> dict:
        path = Path(runbook_path)
        if not path.exists():
            raise FileNotFoundError(f"Runbook not found: {runbook_path}")
        with open(path) as f:
            runbook = yaml.safe_load(f)
        required_keys = ["name", "remediation_steps"]
        for key in required_keys:
            if key not in runbook:
                raise ValueError(f"Runbook missing required key: {key}")
        return runbook

    def run_command(self, command: str, timeout: int = 30) -> tuple:
        if self.dry_run:
            logger.info(f"[DRY RUN] Would execute: {command}")
            return 0, "", ""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s: {command}")
            return 1, "", "TIMEOUT"

    def execute_remediation(self, runbook: dict, target: Optional[str] = None) -> bool:
        name = runbook["name"]
        steps = runbook["remediation_steps"]
        logger.info(f"Executing remediation: {name}")
        if target:
            logger.info(f"Target: {target}")
        for i, step in enumerate(steps, 1):
            step_name = step.get("name", f"Step {i}")
            command = step.get("command", "")
            if target:
                command = command.replace("{{target}}", target)
            logger.info(f"  [{i}/{len(steps)}] {step_name}: {command}")
            returncode, stdout, stderr = self.run_command(
                command,
                timeout=step.get("timeout", 30)
            )
            if returncode != 0:
                logger.error(f"  Step failed: {stderr}")
                if not step.get("continue_on_failure", False):
                    self.failed.append({
                        "runbook": name,
                        "step": step_name,
                        "error": stderr
                    })
                    return False
            else:
                if stdout:
                    logger.info(f"  Output: {stdout}")
            wait = step.get("wait_seconds", 0)
            if wait and not self.dry_run:
                logger.info(f"  Waiting {wait}s...")
                time.sleep(wait)
        self.remediated.append({"runbook": name, "target": target})
        logger.info(f"Remediation complete: {name}")
        return True

    def run_from_file(self, runbook_path: str, target: Optional[str] = None) -> bool:
        runbook = self.load_runbook(runbook_path)
        return self.execute_remediation(runbook, target=target)

    def print_summary(self) -> None:
        print(f"\n{'='*55}")
        print("REMEDIATION SUMMARY")
        print(f"{'='*55}")
        print(f"  Remediated: {len(self.remediated)}")
        print(f"  Failed:     {len(self.failed)}")
        for item in self.remediated:
            print(f"  OK {item['runbook']}" + (f" -> {item['target']}" if item.get('target') else ""))
        for item in self.failed:
            print(f"  FAIL {item['runbook']} — {item['step']}: {item['error']}")
        print(f"{'='*55}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-remediate incidents using runbooks")
    parser.add_argument("--runbook", help="Path to runbook YAML file")
    parser.add_argument("--runbooks-dir", help="Directory of runbook YAML files")
    parser.add_argument("--target", help="Target pod/service name")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    remediator = IncidentRemediator(dry_run=args.dry_run)
    if args.runbook:
        success = remediator.run_from_file(args.runbook, target=args.target)
        remediator.print_summary()
        sys.exit(0 if success else 1)
    elif args.runbooks_dir:
        runbook_dir = Path(args.runbooks_dir)
        if not runbook_dir.exists():
            logger.error(f"Runbooks directory not found: {args.runbooks_dir}")
            sys.exit(1)
        for rb_path in runbook_dir.glob("*.yaml"):
            try:
                remediator.run_from_file(str(rb_path), target=args.target)
            except Exception as e:
                logger.error(f"Failed to process runbook {rb_path}: {e}")
        remediator.print_summary()
        sys.exit(1 if remediator.failed else 0)
    else:
        logger.error("Provide either --runbook or --runbooks-dir")
        sys.exit(1)


if __name__ == "__main__":
    main()
