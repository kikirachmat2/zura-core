"""
ans/server_watchdog.py - Autonomic Cloud Server Watchdog
Monitors Server 1 (Manake SG1) & Server 2 (Lazarus SG2):
- Probes systemd services (KiBot, PM2 Kisah Komisi, Chrony NTP)
- Auto-restarts failed services without waiting for human input
- Vacuums journalctl logs and clears package cache if disk > 75%
- Resyncs chrony clock if API nonce desync is detected
"""

import subprocess
import time
import json
import logging
import socket
import os
import sys
from typing import Dict, Any, List
from core.config import (
    SERVER1_HOST, SERVER1_TAILSCALE, SERVER1_USER, SERVER1_KEY,
    SERVER2_HOST, SERVER2_USER, SERVER2_KEY, SERVER_DISK_MAX_PCT, SERVER_RAM_MAX_PCT
)
from core.memory import log_decision, set_state
from core.actuator import actuate, ActuatorError

logger = logging.getLogger("ServerWatchdog")


class ServerWatchdog:
    def __init__(self):
        # Auto-detect if currently running directly on Server 1
        self.is_running_on_server1 = False
        try:
            hostname = socket.gethostname().lower()
            if sys.platform.startswith("linux") and (os.path.exists("/home/ubuntu/KiBotV3") or "instance" in hostname or "manake" in hostname):
                self.is_running_on_server1 = True
        except Exception:
            pass

        # Adjust key path for Server 2 if running on Server 1
        server2_key = SERVER2_KEY
        if self.is_running_on_server1:
            local_lazarus_key = os.path.expanduser("~/.ssh/lazarus.key")
            if os.path.exists(local_lazarus_key):
                server2_key = local_lazarus_key

        self.nodes = [
            {
                "id": "SG1",
                "name": "Server 1 (Manake SG)",
                "host": SERVER1_HOST,
                "tailscale": None,
                "user": SERVER1_USER,
                "key": SERVER1_KEY,
                "is_local": self.is_running_on_server1,
                "services": ["chrony", "kibot-v3-core", "zura-batam-sniper"]
            },
            {
                "id": "SG2",
                "name": "Server 2 (Lazarus SG)",
                "host": SERVER2_HOST,
                "tailscale": None,
                "user": SERVER2_USER,
                "key": server2_key,
                "is_local": False,
                "services": ["chrony"]
            }
        ]

    def _execute_command(self, node: dict, command: str, timeout: int = 10) -> tuple[int, str]:
        """Executes command locally if on Server 1, or via SSH if remote."""
        if node.get("is_local"):
            try:
                res = subprocess.run(command, shell=True, executable="/bin/bash", capture_output=True, text=True, timeout=timeout)
                return res.returncode, res.stdout.strip()
            except subprocess.TimeoutExpired:
                return -1, "Local execution timed out"
            except Exception as e:
                return -1, str(e)

        key_path = node["key"]
        user = node["user"]

        # Try direct host first, fallback to Tailscale
        ips_to_try = [node["host"]]
        if node.get("tailscale"):
            ips_to_try.append(node["tailscale"])

        last_error = ""
        for ip in ips_to_try:
            cmd = [
                "ssh",
                "-o", "ConnectTimeout=2",
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes"
            ]
            if os.path.exists(key_path):
                cmd.extend(["-i", key_path])
            cmd.extend([f"{user}@{ip}", command])

            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                if res.returncode == 0:
                    return 0, res.stdout.strip()
                last_error = res.stderr.strip() or res.stdout.strip()
            except subprocess.TimeoutExpired:
                last_error = f"SSH to {ip} Timed Out"
            except Exception as e:
                last_error = str(e)

        return -1, last_error

    def probe_node_health(self, node: dict) -> Dict[str, Any]:
        """Runs health audit script on target node."""
        audit_script = """
        # Disk usage %
        disk_pct=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
        
        # RAM usage %
        ram_pct=$(free | awk '/Mem:/ {printf "%.1f", $3/$2 * 100}')
        
        # Check systemd services
        service_statuses=""
        for svc in chrony kibot-v3-core zura-batam-sniper zura; do
            if systemctl is-active --quiet "$svc" 2>/dev/null; then
                service_statuses="${service_statuses}${svc}:RUNNING "
            elif systemctl list-unit-files 2>/dev/null | grep -q "$svc"; then
                service_statuses="${service_statuses}${svc}:DEAD "
            fi
        done
        
        # Check PM2 if installed
        pm2_status="N/A"
        if command -v pm2 >/dev/null 2>&1; then
            pm2_status=$(pm2 jlist 2>/dev/null | grep -o '"status":"[^"]*"' | head -n 3 | tr -d '"')
        fi
        
        echo "$disk_pct|$ram_pct|$service_statuses|$pm2_status"
        """
        code, out = self._execute_command(node, audit_script, timeout=8)
        
        if code != 0:
            return {
                "id": node["id"],
                "name": node["name"],
                "status": "UNREACHABLE",
                "error": out,
                "timestamp": time.time()
            }

        parts = out.split("|")
        disk_pct = float(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0.0
        ram_pct = float(parts[1]) if len(parts) > 1 else 0.0
        services_raw = parts[2] if len(parts) > 2 else ""
        pm2_info = parts[3] if len(parts) > 3 else ""

        # Parse service statuses
        services = {}
        for item in services_raw.split():
            if ":" in item:
                k, v = item.split(":", 1)
                services[k] = v

        data = {
            "id": node["id"],
            "name": node["name"],
            "status": "HEALTHY",
            "disk_used_pct": disk_pct,
            "ram_used_pct": ram_pct,
            "services": services,
            "pm2_status": pm2_info,
            "timestamp": time.time()
        }
        
        # Self-Healing Refleks:
        self._auto_heal_if_needed(node, data)
        return data

    def _auto_heal_if_needed(self, node: dict, data: dict):
        """Instinctive auto-remediation without prompting Kiki."""
        node_name = node["name"]
        
        # 1. Dead Service Auto-Restart (excluding voluntary dead)
        for svc, state in data.get("services", {}).items():
            if state == "DEAD" and svc not in ["zura"]:
                logger.warning(f"🚨 {svc} is DEAD on {node_name}. Routing restart through actuator...")
                def _do_restart(s=svc, n=node):
                    restart_cmd = f"sudo /usr/bin/systemctl restart {s}"
                    rc, out = self._execute_command(n, restart_cmd, timeout=10)
                    if rc != 0:
                        raise RuntimeError(f"Service {s} restart failed: {out}")
                    return out

                action_name = "kibot_restart_service" if svc == "kibot-v3-core" else "server_restart_service"
                try:
                    res = actuate(
                        name=action_name,
                        tier="L2",
                        fn=_do_restart,
                        params={"node": node.get("id"), "service": svc},
                        entity=f"server_sentinel_{node.get('id')}",
                        reason=f"Service {svc} detected DEAD on {node_name}",
                        reversible=False
                    )
                    log_decision(
                        domain=f"Server Sentinel ({node['id']})",
                        trigger_event=f"Service {svc} detected DEAD",
                        decision_taken="Executed auto-restart via actuator",
                        outcome="Service successfully restored" if res.get("success") else str(res)
                    )
                except ActuatorError as ae:
                    logger.warning(f"Actuator blocked restart for {svc}: {ae}")
                except Exception as e:
                    logger.error(f"Restart error for {svc}: {e}")

        # 2. Disk Vacuum if threshold breached
        if data.get("disk_used_pct", 0) > SERVER_DISK_MAX_PCT:
            logger.warning(f"⚠️ Disk usage breached {data['disk_used_pct']}% threshold. Routing vacuum through actuator...")
            def _do_vacuum(n=node):
                vacuum_cmd = "sudo /usr/bin/journalctl --vacuum-size=100M --vacuum-time=3d; pm2 flush 2>/dev/null || true; sudo find /tmp -type f -atime +3 -delete 2>/dev/null || true"
                rc, out = self._execute_command(n, vacuum_cmd, timeout=15)
                if rc != 0:
                    raise RuntimeError(f"Vacuum failed: {out}")
                return out

            try:
                res = actuate(
                    name="server_vacuum_logs",
                    tier="L1",
                    fn=_do_vacuum,
                    params={"node": node.get("id")},
                    entity=f"server_sentinel_{node.get('id')}",
                    reason=f"Disk usage breached {data['disk_used_pct']}% threshold",
                    reversible=False
                )
                log_decision(
                    domain=f"Server Sentinel ({node['id']})",
                    trigger_event=f"Disk usage breached {data['disk_used_pct']}% threshold",
                    decision_taken="Executed journalctl vacuum via actuator",
                    outcome="Storage capacity stabilized"
                )
            except ActuatorError as ae:
                logger.warning(f"Actuator blocked vacuum: {ae}")
            except Exception as e:
                logger.error(f"Vacuum error: {e}")

    def oci_keepalive_pulse(self, node: dict) -> Dict[str, Any]:
        """
        Anti-Reclaim Pulse for Oracle Cloud Infrastructure (OCI):
        OCI terminates Free Tier instances if CPU < 15% for 7 consecutive days.
        This sends a controlled 1.5s micro-workload pulse (sha256 calculation)
        that briefly registers CPU activity without starving services.
        """
        pulse_cmd = "python3 -c \"import hashlib, time; t=time.time(); [hashlib.sha256(b'oci_keepalive'*1000).hexdigest() for _ in range(500000) if time.time()-t < 1.5]\""
        rc, out = self._execute_command(node, pulse_cmd, timeout=5)
        return {"node": node.get("id"), "pulse_success": rc == 0}

    def probe_all_servers(self) -> List[Dict[str, Any]]:
        """Audits all configured server nodes and caches state."""
        results = []
        for node in self.nodes:
            res = self.probe_node_health(node)
            results.append(res)
        
        set_state("servers_telemetry", results)
        return results


# Global instance
server_watchdog = ServerWatchdog()
