#!/usr/bin/env python3
"""
Centreon plugin example for LGM Receiver metrics endpoint.
"""

import argparse
import sys
from typing import Dict

import requests


def exit_with(code: int, text: str) -> None:
    print(text)
    raise SystemExit(code)


def check_threshold(value: float, warning: float, critical: float) -> int:
    if value >= critical:
        return 2
    if value >= warning:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Centreon plugin for LGM metrics")
    parser.add_argument("--url", required=True, help="Receiver base URL, ex: https://receiver:8443")
    parser.add_argument("--token", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--warning-cpu", type=float, default=80)
    parser.add_argument("--critical-cpu", type=float, default=90)
    parser.add_argument("--warning-mem", type=float, default=80)
    parser.add_argument("--critical-mem", type=float, default=90)
    parser.add_argument("--warning-disk", type=float, default=80)
    parser.add_argument("--critical-disk", type=float, default=90)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    args = parser.parse_args()

    try:
        response = requests.get(
            f"{args.url.rstrip('/')}/metrics",
            params={"host": args.host},
            headers={"X-Agent-Token": args.token},
            timeout=args.timeout,
            verify=not args.insecure,
        )
    except requests.RequestException as exc:
        exit_with(3, f"UNKNOWN - request failed: {exc}")

    if response.status_code != 200:
        exit_with(3, f"UNKNOWN - API returned {response.status_code}: {response.text[:200]}")

    payload: Dict = response.json().get("data", {})
    metrics = payload.get("metrics") or {}
    if not metrics:
        exit_with(3, "UNKNOWN - missing metrics payload")

    cpu = float(metrics.get("cpu", 0))
    mem = float(metrics.get("memory", 0))
    disk = float(metrics.get("disk", 0))

    status = max(
        check_threshold(cpu, args.warning_cpu, args.critical_cpu),
        check_threshold(mem, args.warning_mem, args.critical_mem),
        check_threshold(disk, args.warning_disk, args.critical_disk),
    )

    labels = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}
    text = (
        f"{labels[status]} - cpu {cpu:.1f}% mem {mem:.1f}% disk {disk:.1f}% "
        f"| cpu={cpu:.1f};{args.warning_cpu};{args.critical_cpu};0;100 "
        f"mem={mem:.1f};{args.warning_mem};{args.critical_mem};0;100 "
        f"disk={disk:.1f};{args.warning_disk};{args.critical_disk};0;100"
    )
    exit_with(status, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
