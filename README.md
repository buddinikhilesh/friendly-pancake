# sre-observability-toolkit

Python SRE automation toolkit for distributed systems reliability.
Built from real production patterns used at enterprise scale.

## What is in this repo

| Script | What it does |
|---|---|
| `slo_tracker.py` | Tracks SLO/SLI error budget burn rate across services |
| `workload_health_monitor.py` | Detects stalled and degraded long-running distributed jobs |
| `incident_remediator.py` | Auto-remediates known recurring incidents via runbook automation |
| `runbooks/high-memory.yaml` | Sample runbook for high memory pod auto-restart |

## Why I built this

Managing 30+ production microservices at Southwest Airlines the biggest
problems were alert noise, repeat incidents, and manual toil.
These scripts solved those problems — converting 80% of repeat incidents
into permanent automated fixes and reducing alert noise by 35%.

## Usage

```bash
pip install -r requirements.txt

# Track SLO burn rate
python slo_tracker.py --service payment-api --window 30d --slo 99.9

# Monitor long-running workload health
python workload_health_monitor.py --namespace production --timeout 300

# Run auto-remediation
python incident_remediator.py --runbook runbooks/high-memory.yaml --dry-run
```

## Related resume projects
- Project PulseEngine — SRE observability platform at Southwest Airlines
- ReliabilityCore — SLO/SLI framework rollout at Cognizant
- AlertStack — monitoring modernisation at Spring Info Tech
