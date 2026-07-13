import os
import sys
import json
import subprocess
import shutil
from datetime import datetime, timedelta

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DIR = os.path.dirname(PLUGIN_DIR)
HDD_PATH = os.path.join(SANDBOX_DIR, "core_memory", "dom_hdd.json")

def load_system_data():
    if os.path.exists(HDD_PATH):
        try:
            with open(HDD_PATH, "r") as f:
                return json.load(f)
        except: pass
    return {}

def save_system_data(data):
    try:
        with open(HDD_PATH, "w") as f:
            json.dump(data, f, indent=4)
    except: pass

def run_command(cmd, desc):
    print(f"[Maintenance]: {desc}...", file=sys.stderr, flush=True)
    try:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

def execute_maintenance():
    hdd_data = load_system_data()
    now = datetime.now()
    
    # Check timings for the comprehensive weekly components
    last_big_clean_str = hdd_data.get("last_weekly_maintenance", "")
    run_weekly = False
    
    if last_big_clean_str:
        try:
            last_clean = datetime.strptime(last_big_clean_str, "%Y-%m-%d")
            if now - last_clean >= timedelta(days=7):
                run_weekly = True
        except:
            run_weekly = True
    else:
        run_weekly = True

    print("\n--- INITIATING DOM ADVANCED MULTI-LAYER MAINTENANCE ---", file=sys.stderr)
    
    # =========================================================================
    # 1. DAILY MINI CLEAN (Runs Every Single Call)
    # =========================================================================
    # Vacuum systemd log journals down to exactly 500 Megabytes
    run_command("sudo journalctl --vacuum-size=500M", "Vacuuming Systemd Journal Logs to 500MB")
    
    # Clear orphaned dead Pacman database lock files
    if os.path.exists("/var/lib/pacman/db.lck"):
        check_proc = subprocess.run("pgrep pacman", shell=True, stdout=subprocess.PIPE)
        if check_proc.returncode != 0:
            run_command("sudo rm /var/lib/pacman/db.lck", "Vaporizing orphaned Pacman database lockfile")
            
    # Purge crashed system application core-dumps taking up space
    run_command("sudo rm -rf /var/lib/systemd/coredump/*", "Scrubbing system core dump log crash files")
    
    # Audit background systemd unit failure triggers
    run_command("systemctl --failed --quiet", "Auditing system services for operational failures")

    # Wipe local application hidden thumbnail caches
    thumb_path = os.path.expanduser("~/.cache/thumbnails")
    if os.path.exists(thumb_path):
        run_command(f"rm -rf {thumb_path}/*", "Flushing user environment thumbnail image cache")

    # Runtime check: Track remaining root storage threshold metrics
    total, used, free = shutil.disk_usage("/")
    free_percent = (free / total) * 100
    if free_percent < 12.0:
        print(f"[CRITICAL WARNING]: Storage space running dangerous! Only {free_percent:.1f}% space left on root partition.", file=sys.stderr)

    # =========================================================================
    # 2. COMPREHENSIVE WEEKLY PURGE (Runs Once Every 7 Days)
    # =========================================================================
    if run_weekly:
        print("\n[Schedule Notice]: Running Comprehensive Weekly System Optimization Sequence...", file=sys.stderr)
        
        # Strip out unreferenced orphan dependencies no longer needed by any app
        check_orphans = subprocess.run("pacman -Qdtq", shell=True, stdout=subprocess.PIPE, text=True)
        if check_orphans.stdout.strip():
            run_command("sudo pacman -Rns $(pacman -Qdtq) --noconfirm", "Eradicating orphaned system dependencies")
        else:
            print("[Maintenance]: No system orphans detected.", file=sys.stderr)
        
        # Clean pacman local installation archive down to last 2 safe fallback states
        run_command("sudo paccache -r", "Trimming archived Pacman installer installer packages")
        
        # Manjaro Optimization: Re-rank the top 5 fastest mirror servers nearby to speed up downloads
        run_command("sudo pacman-mirrors -f 5", "Re-ranking and refreshing top 5 fastest local network update mirrors")
        
        hdd_data["last_weekly_maintenance"] = now.strftime("%Y-%m-%d")
    
    # Log run details into persistent hdd architecture metrics
    hdd_data["last_maintenance_sweep"] = now.strftime("%Y-%m-%d %H:%M:%S")
    save_system_data(hdd_data)
    
    print("--- DOM AUTOMATED MAINTENANCE SYSTEM RUN COMPLETELY OVER --- \n", file=sys.stderr, flush=True)

if __name__ == "__main__":
    execute_maintenance()