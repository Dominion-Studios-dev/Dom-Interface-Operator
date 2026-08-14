"""Resource Guard — thermal & resource health watchdog.

Extends the telemetry framework: parses real hardware stats, compares them
against safety thresholds, and fires an ntfy.sh push alert the instant a
limit is breached. Runs entirely offline for detection (ntfy needs network).

Commands:
    check temps      Thermal + load + disk + memory health report
    system health    Same as above
    thermal check    Same as above

Thresholds (override via env vars):
    RG_CPU_TEMP_MAX    85  (Celsius)
    RG_CPU_LOAD_MAX    85  (percent)
    RG_DISK_USED_MAX   90  (percent)
    RG_MEM_USED_MAX    90  (percent)

All subprocess calls use argv lists (no shell) and output is locale-safe.
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.request

from modules.base import BasePlugin

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

NTFY_URL = "https://ntfy.sh/dom-interface"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


CPU_TEMP_MAX = _env_float("RG_CPU_TEMP_MAX", 85.0)
CPU_LOAD_MAX = _env_float("RG_CPU_LOAD_MAX", 85.0)
DISK_USED_MAX = _env_float("RG_DISK_USED_MAX", 90.0)
MEM_USED_MAX = _env_float("RG_MEM_USED_MAX", 90.0)


def _run(argv, timeout=8):
    try:
        r = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return (r.stdout + r.stderr)
    except Exception:
        return ""


def _to_float(value: str) -> float:
    """Parse a number, tolerating comma decimal separators (e.g. 26,9)."""
    if not value:
        return 0.0
    try:
        return float(value.replace(",", ".").strip())
    except ValueError:
        return 0.0


def _cpu_temp() -> float:
    """Max package/core temperature from `sensors` output. 0.0 = unknown."""
    raw = _run(["sensors"])
    temps = []
    pattern = re.compile(
        r"^(?:Package id \d+|Core \d+|Tctl|Tdie|Tccd\d+|Composite|temp1|hotspot):\s*\+?([0-9.,]+)\s*°C",
        re.IGNORECASE | re.MULTILINE,
    )
    for m in pattern.finditer(raw):
        temps.append(_to_float(m.group(1)))
    return max(temps) if temps else 0.0


def _cpu_load() -> float:
    """Current CPU busy percent from `top`. 0.0 = unknown."""
    raw = _run(["top", "-bn1"])
    idle_m = re.search(r"([0-9.,]+)\s*id", raw)
    if idle_m:
        idle = _to_float(idle_m.group(1))
        return max(0.0, min(100.0, 100.0 - idle))
    us_m = re.search(r"([0-9.,]+)\s*us", raw)
    if us_m:
        return max(0.0, min(100.0, _to_float(us_m.group(1))))
    return 0.0


def _mem_used() -> float:
    """Memory used percent from /proc/meminfo. 0.0 = unknown."""
    try:
        with open("/proc/meminfo") as f:
            data = f.read()
        total_m = re.search(r"MemTotal:\s+(\d+)", data)
        avail_m = re.search(r"MemAvailable:\s+(\d+)", data)
        if total_m and avail_m:
            total = float(total_m.group(1))
            avail = float(avail_m.group(1))
            if total > 0:
                return max(0.0, min(100.0, ((total - avail) / total) * 100.0))
    except Exception:
        pass
    return 0.0


def _disk_used() -> float:
    """Root partition used percent via shutil (no shell)."""
    try:
        usage = shutil.disk_usage("/")
        return max(0.0, min(100.0, (usage.used / usage.total) * 100.0))
    except Exception:
        return 0.0


def _ntfy_alert(title: str, body: str) -> bool:
    try:
        req = urllib.request.Request(
            NTFY_URL,
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Tags": "warning,rotating_light",
                "Priority": "high",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def _fmt(value: float, suffix="") -> str:
    return f"{value:.1f}{suffix}"


def run_health_check() -> dict:
    cpu_temp = _cpu_temp()
    cpu_load = _cpu_load()
    mem_used = _mem_used()
    disk_used = _disk_used()

    breaches = []
    if cpu_temp > 0 and cpu_temp > CPU_TEMP_MAX:
        breaches.append(f"CPU temperature {_fmt(cpu_temp, '°C')} exceeds {CPU_TEMP_MAX:.0f}°C limit")
    if cpu_load > 0 and cpu_load > CPU_LOAD_MAX:
        breaches.append(f"CPU load {_fmt(cpu_load, '%')} exceeds {CPU_LOAD_MAX:.0f}% limit")
    if disk_used > 0 and disk_used > DISK_USED_MAX:
        breaches.append(f"Disk usage {_fmt(disk_used, '%')} exceeds {DISK_USED_MAX:.0f}% limit")
    if mem_used > 0 and mem_used > MEM_USED_MAX:
        breaches.append(f"Memory usage {_fmt(mem_used, '%')} exceeds {MEM_USED_MAX:.0f}% limit")

    lines = ["── Resource Guard Report ──"]
    lines.append(f"CPU:       {_fmt(cpu_load, '%')} load | temp {_fmt(cpu_temp, '°C')}")
    lines.append(f"Memory:    {_fmt(mem_used, '%')} used")
    lines.append(f"Disk ( / ): {_fmt(disk_used, '%')} used")
    lines.append(f"Limits:    temp>{CPU_TEMP_MAX:.0f}°C  load>{CPU_LOAD_MAX:.0f}%  disk>{DISK_USED_MAX:.0f}%  mem>{MEM_USED_MAX:.0f}%")

    if not breaches:
        lines.append("")
        lines.append("Status: ALL NOMINAL — no thresholds breached.")
        return {"status": "success", "output": "\n".join(lines)}

    lines.append("")
    lines.append("⚠ ALERT: threshold breached!")
    for b in breaches:
        lines.append(f"  - {b}")

    alert_body = "\n".join(b for b in breaches)
    sent = _ntfy_alert("Dom Resource Guard", alert_body)
    lines.append("")
    lines.append("ntfy.sh push: " + ("DELIVERED" if sent else "FAILED (offline?)"))
    return {"status": "success", "output": "\n".join(lines)}


class Plugin(BasePlugin):
    name = "resource_guard"
    triggers = [
        "check temps", "system health", "thermal check", "thermal",
        "check temperature", "health check", "overheating", "resource guard",
        "temperature check", "check temps",
    ]

    def execute(self, user_input: str) -> dict:
        lower = user_input.lower().strip()
        if not lower:
            return {"status": "error", "output": "Empty query."}
        return run_health_check()
