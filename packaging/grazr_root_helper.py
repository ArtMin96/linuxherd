#!/usr/bin/env python3
"""
Grazr Root Helper

A minimal utility providing systemd service check capability.
No longer used for Nginx control or hosts file editing at runtime.

Last updated: Tuesday, April 22, 2025
"""

import sys
import subprocess
import argparse
import shlex
import os
import tempfile
from pathlib import Path
import re

# Security Configuration
# ----------------------------------------------------------------------------
# Services that are allowed to be checked
ALLOWED_SERVICES = [
    "dnsmasq.service",
    "nginx.service",    # Keep for conflict checking
    "apache2.service",
    # Add php*-fpm services?
]

# Only allow read-only operations
ALLOWED_ACTIONS = [
    # systemd actions
    "status", "is-active", "is-enabled", "is-failed",
    # Hosts file actions
    "add_host_entry",
    "remove_host_entry",
]


# Helper Functions
# ----------------------------------------------------------------------------
def log_error(message):
    """Log an error message to stderr."""
    print(f"Helper Error: {message}", file=sys.stderr)


def log_info(message):
    """Log an informational message to stderr."""
    print(f"Helper Info: {message}", file=sys.stderr)

def validate_domain_name(domain_name): # (Keep validation)
    if not domain_name or not isinstance(domain_name, str): return False
    if not re.match(r'^[a-zA-Z0-9.\-]+$', domain_name): return False
    if ".." in domain_name or domain_name.startswith("/") or domain_name.endswith("."): return False
    if len(domain_name) > 253: return False
    return True

def validate_ip_address(ip_address): # (Keep validation)
    if not ip_address or not isinstance(ip_address, str): return False
    if ip_address == "127.0.0.1" or re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address): return True
    return False

# Action Handlers
# ----------------------------------------------------------------------------
def handle_systemctl_check(service, action, systemctl_path):
    """
    Run a read-only systemctl command.
    
    Args:
        service: The systemd service name to check
        action: The systemctl action to perform
        
    Returns:
        Exits with the systemctl return code
    """
    if service not in ALLOWED_SERVICES: log_error(f"Service '{service}' not allowed."); sys.exit(10)
    if action not in ALLOWED_ACTIONS or action not in ["status", "is-active", "is-enabled", "is-failed"]: log_error(
        f"Action '{action}' not allowed."); sys.exit(11)
    if not Path(systemctl_path).is_file(): log_error(f"systemctl path invalid: {systemctl_path}"); sys.exit(12)

    command = [systemctl_path, action, service]  # Use provided path
    log_info(f"Executing: {shlex.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        log_info(f"systemctl result code: {result.returncode}")
        output = result.stdout.strip() or result.stderr.strip() or f"Completed code {result.returncode}"
        print(f"Helper Result: {output}");
        sys.exit(result.returncode)
    except Exception as e:
        log_error(f"systemctl failed: {e}"); sys.exit(4)

def handle_add_host_entry(ip_address, domain_name, hosts_path_str, hosts_marker): # Takes path/marker args
    """Adds an entry to the specified hosts file."""
    log_info(f"Adding host entry: {ip_address} {domain_name} to {hosts_path_str}")
    if not validate_domain_name(domain_name) or not validate_ip_address(ip_address): sys.exit(70)

    entry = f"{ip_address}\t{domain_name}\t{hosts_marker}" # Use provided marker
    host_file = Path(hosts_path_str) # Use provided path
    temp_path = None
    try:
        lines = host_file.read_text(encoding='utf-8').splitlines(keepends=True) if host_file.exists() else []
        domain_pattern = re.compile(r"^\s*" + re.escape(ip_address) + r"\s+.*?" + re.escape(domain_name) + r"(?:\s+|#|$)")
        entry_found = any(not line.strip().startswith('#') and domain_pattern.search(line) for line in lines)

        if not entry_found:
            log_info("Adding new line.");
            if lines and not lines[-1].endswith('\n'): lines.append('\n')
            lines.append(entry + '\n')
            fd, temp_path = tempfile.mkstemp(dir=host_file.parent, prefix='hosts.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as temp_f: temp_f.writelines(lines)
            stat_info = host_file.stat() if host_file.exists() else None
            if stat_info: os.chmod(temp_path, stat_info.st_mode)
            os.replace(temp_path, host_file); temp_path = None
            log_info("Added entry."); print(f"Helper: Added {domain_name} to {hosts_path_str}.")
        else:
             log_info(f"Entry already exists."); print(f"Helper: Entry for {domain_name} exists.")
        sys.exit(0)

    except Exception as e: log_error(f"Failed updating {host_file}: {e}"); sys.exit(71)
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.unlink(temp_path)
            except OSError as e: log_error(f"Failed removing temp file {temp_path}: {e}")


def handle_remove_host_entry(domain_name, hosts_path_str, hosts_marker): # Takes path/marker args
    """Removes entries associated with a domain name and marker from specified hosts file."""
    log_info(f"Removing host entries for: {domain_name} from {hosts_path_str}")
    if not validate_domain_name(domain_name): sys.exit(72)

    host_file = Path(hosts_path_str); temp_path = None
    try:
        if not host_file.is_file(): log_info("Hosts file not found."); print("Helper: Hosts file not found."); sys.exit(0)
        lines = host_file.read_text(encoding='utf-8').splitlines(keepends=True)
        domain_pattern = re.compile(r"\s+" + re.escape(domain_name) + r"(?:\s+|#|$)")
        lines_to_keep = []; removed_count = 0
        for line in lines:
            # Use provided marker for removal check
            if line.strip().startswith('#') or not (hosts_marker in line and domain_pattern.search(line)):
                lines_to_keep.append(line)
            else: log_info(f"Removing: {line.strip()}"); removed_count += 1

        if removed_count > 0:
            log_info(f"Removed {removed_count} entries. Writing updated file.");
            fd, temp_path = tempfile.mkstemp(dir=host_file.parent, prefix='hosts.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as temp_f: temp_f.writelines(lines_to_keep)
            stat_info = host_file.stat(); os.chmod(temp_path, stat_info.st_mode);
            os.replace(temp_path, host_file); temp_path = None
            print(f"Helper: Removed {domain_name} from {hosts_path_str}.")
        else: log_info("No matching entries found."); print(f"Helper: Entry for {domain_name} not found.")
        sys.exit(0)

    except Exception as e: log_error(f"Failed updating {host_file}: {e}"); sys.exit(73)
    finally:
        if temp_path and os.path.exists(temp_path):
            try: os.unlink(temp_path)
            except OSError as e: log_error(f"Failed removing temp file {temp_path}: {e}")


# Main Entry Point
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Root Helper: Manages system checks and hosts file.")
    # Action and Service for systemd checks
    parser.add_argument("--action", required=True, choices=ALLOWED_ACTIONS)
    parser.add_argument("--service", required=False, choices=ALLOWED_SERVICES + [None])
    # Arguments for Hosts file actions (passed from main app via system_utils)
    parser.add_argument("--domain", required=False, help="Domain name for hosts file actions")
    parser.add_argument("--ip", required=False, default="127.0.0.1", help="IP address for add_host_entry")
    parser.add_argument("--hosts-path", required=False, help="Path to the hosts file (e.g., /etc/hosts)")
    parser.add_argument("--hosts-marker", required=False, help="Comment marker for hosts file entries")
    # Argument for systemctl path
    parser.add_argument("--systemctl-path", required=False, help="Path to the systemctl executable")

    args = parser.parse_args();
    action = args.action

    try:
        if action in ["status", "is-active", "is-enabled", "is-failed"]:
            if not args.service: raise ValueError(f"Action '{action}' requires --service.")
            if not args.systemctl_path: raise ValueError(f"Action '{action}' requires --systemctl-path.")
            handle_systemctl_check(args.service, action, args.systemctl_path)

        elif action == "add_host_entry":
            if not args.domain: raise ValueError(f"Action '{action}' requires --domain.")
            if not args.hosts_path: raise ValueError(f"Action '{action}' requires --hosts-path.")
            if not args.hosts_marker: raise ValueError(f"Action '{action}' requires --hosts-marker.")
            handle_add_host_entry(args.ip, args.domain, args.hosts_path, args.hosts_marker)

        elif action == "remove_host_entry":
            if not args.domain: raise ValueError(f"Action '{action}' requires --domain.")
            if not args.hosts_path: raise ValueError(f"Action '{action}' requires --hosts-path.")
            if not args.hosts_marker: raise ValueError(f"Action '{action}' requires --hosts-marker.")
            handle_remove_host_entry(args.domain, args.hosts_path, args.hosts_marker)

        else:
            raise ValueError(f"Unsupported action '{action}'.")

    except ValueError as e:
        log_error(str(e)); sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}"); sys.exit(99)
