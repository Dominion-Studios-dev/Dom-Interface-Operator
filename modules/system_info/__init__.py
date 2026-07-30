"""System Info — hardware reports, system maintenance, optimization."""

import os
import subprocess

from modules.base import BasePlugin
from modules.util import (
    SCRIPT_DIR, CYAN, GREEN, DIM, RESET,
    log_info, log_err, log_warn, run_cmd, run_with_spinner, print_box,
)


HW_KEYWORDS = [
    "hardware", "specs", "spec", "cpu", "gpu", "ram", "memory", "disk",
    "drive", "ssd", "nvme", "temperature", "temp", "usage", "load",
    "nvidia", "geforce", "gtx", "rtx", "intel", "amd", "system info",
    "machine", "monitor", "network", "wifi", "ethernet", "probe",
    "system stats", "what are my", "tell me about", "my pc", "my computer",
    "how much", "what gpu", "what cpu", "what ram",
]


def gather_system_metrics() -> str:
    """Gather REAL hardware specs from the local machine."""
    lines = []

    cpu_model = run_cmd("lscpu | grep 'Model name' | sed 's/Model name:\\s*//'")
    cpu_cores = run_cmd("nproc")
    cpu_usage = run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
    if cpu_model:
        lines.append(f"CPU: {cpu_model} ({cpu_cores} cores, {cpu_usage}% usage)")

    ram_total = run_cmd("free -h | awk '/^Mem:/{print $2}'")
    ram_used = run_cmd("free -h | awk '/^Mem:/{print $3}'")
    ram_free = run_cmd("free -h | awk '/^Mem:/{print $4}'")
    if ram_total:
        lines.append(f"RAM: {ram_total} total, {ram_used} used, {ram_free} free")

    gpu = run_cmd("nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null")
    if gpu:
        lines.append(f"GPU: {gpu}")
    else:
        gpu_lspci = run_cmd("lspci | grep -i 'vga\\|3d' | head -1")
        if gpu_lspci:
            lines.append(f"GPU: {gpu_lspci}")

    disk_total = run_cmd("df -h / | awk 'NR==2{print $2}'")
    disk_used = run_cmd("df -h / | awk 'NR==2{print $3}'")
    disk_free = run_cmd("df -h / | awk 'NR==2{print $4}'")
    disk_pct = run_cmd("df -h / | awk 'NR==2{print $5}'")
    if disk_total:
        lines.append(f"Disk: {disk_total} total, {disk_used} used, {disk_free} free ({disk_pct} used)")

    os_info = run_cmd("cat /etc/os-release | grep PRETTY_NAME | cut -d'\"' -f2")
    kernel = run_cmd("uname -r")
    if os_info:
        lines.append(f"OS: {os_info} (Kernel {kernel})")

    uptime = run_cmd("uptime -p")
    if uptime:
        lines.append(f"Uptime: {uptime}")

    return "\n".join(lines) if lines else "System metrics unavailable."


def is_hw_query(message: str) -> bool:
    """Detect if a user message is asking about hardware/system specs."""
    msg = message.lower()
    return any(kw in msg for kw in HW_KEYWORDS)


def inject_system_context(message: str) -> str:
    """Prepend real system metrics to a message for the cloud LLM."""
    metrics = gather_system_metrics()
    return (
        f"[REAL SYSTEM METRICS — these are the actual hardware specs of Master Ardis's machine. "
        f"Use ONLY this data. Do NOT guess or invent any numbers.]\n"
        f"{metrics}\n\n"
        f"User question: {message}"
    )


def _run_maintenance():
    """Execute the system maintenance plugin."""
    script = os.path.join(SCRIPT_DIR, "dom_cloud", "plugins", "maintain.py")
    if not os.path.exists(script):
        return {"status": "error", "output": f"Maintenance plugin not found: {script}"}
    log_info("Initiating system maintenance...")
    result = run_with_spinner("Running maintenance", subprocess.run,
                              ["python3", "-u", script], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True)
    if result.returncode == 0:
        body = result.stdout.strip() or result.stderr.strip() or "Maintenance completed successfully."
        return {"status": "success", "output": body}
    else:
        log_err("Maintenance failed: Missing passwordless sudo permissions.")
        log_warn("Run 'sudo visudo /etc/sudoers.d/ardis_nopasswd' to allow passwordless execution.")
        return {"status": "error", "output": "Missing passwordless sudo permissions."}


def _run_hardware_report():
    """Gather and display hardware metrics."""
    log_info("Gathering system metrics...")
    metrics = run_with_spinner("Scanning hardware", gather_system_metrics)
    return {"status": "success", "output": metrics}


class Plugin(BasePlugin):
    name = "system_info"
    triggers = [
        "system", "maintenance", "optimize", "clean system",
        "/hw", "/specs", "/hardware",
    ]

    def execute(self, user_input: str) -> dict:
        lower = user_input.lower().strip()

        if lower in ["/hw", "/specs", "/hardware"]:
            return _run_hardware_report()

        if any(w in lower for w in ["system", "maintenance", "optimize", "clean system"]):
            return _run_maintenance()

        return {"status": "error", "output": "Unknown system command."}
