#!/usr/bin/env python3
"""Raspberry Pi restoration manifest generator and dotfile archiver.

Generates ./output/pi-YYYYMMDD.json (and ./output/pi-date.json) capturing:
- Running and enabled systemd services and timers (system and user scopes).
- Cross-reference against ~/WebApps/services.md.
- User and system cron entries.
- Nginx sites-enabled configurations, locations, and referenced snippets.
- Every Git repository under ~/WebApps and ~/jobrunner.
- Secret, token, key, and password file paths (paths only, never contents).
- Step-by-step restoration notes in UK English.
- Optional --dotfiles mode copying non-secret dotfiles into ./output/dotfiles/.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

HOME_DIR = Path.home()
DEFAULT_WEBAPPS_DIR = HOME_DIR / "WebApps"
DEFAULT_JOBRUNNER_DIR = HOME_DIR / "jobrunner"
DEFAULT_SERVICES_MD = DEFAULT_WEBAPPS_DIR / "services.md"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Patterns used to detect and redact inline secrets or reject secret files in --dotfiles mode.
SECRET_FILENAME_PATTERNS = (
    re.compile(r"^\.env($|\.(?!example$|sample$|template$))", re.IGNORECASE),
    re.compile(r"^id_(rsa|ed25519|ecdsa|dsa)", re.IGNORECASE),
    re.compile(r"^authorized_keys?$", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx|gpg|asc|kdbx)$", re.IGNORECASE),
    re.compile(r"^\.htpasswd", re.IGNORECASE),
    re.compile(r"credentials", re.IGNORECASE),
    re.compile(r"^hosts\.yml$", re.IGNORECASE),
    re.compile(r"access[-_]?token", re.IGNORECASE),
    re.compile(r"^\.cli-m365", re.IGNORECASE),
    re.compile(r"^duck\.sh$", re.IGNORECASE),
)

SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[0-9A-Za-z-]{10,})\b"),
)

INLINE_SECRET_ENV_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|AUTH_KEY)[A-Z0-9_]*)\s*=\s*([^\s\"']+|\"[^\"]*\"|'[^']*')"
)

URL_CREDENTIAL_RE = re.compile(r"(https?://)([^/@\s]+:[^/@\s]+)@")

# Safe, non-secret dotfiles relative to HOME_DIR for --dotfiles mode.
DEFAULT_DOTFILES = (
    ".bashrc",
    ".profile",
    ".zshrc",
    ".gitconfig",
    ".gitconfig-personal",
    ".gitconfig-wta",
    ".tmux.conf",
    ".vimrc",
    ".vim_runtime/my_configs.vim",
    ".ssh/config",
    ".config/fish/config.fish",
    ".config/fish/fish_variables",
    ".config/fish/functions",
    ".config/fish/conf.d",
    ".config/fish/completions",
    ".config/git/ignore",
    ".config/systemd/user/pass-secret-service.service",
    ".config/nvim",
)


def _run_cmd(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a subprocess command safely and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


def sanitize_text(text: str) -> str:
    """Redact any embedded URL credentials or inline secret assignments from a string."""
    if not text:
        return text
    cleaned = URL_CREDENTIAL_RE.sub(r"\1<REDACTED>@", text)
    cleaned = INLINE_SECRET_ENV_RE.sub(r"\1=<REDACTED>", cleaned)
    for pat in SECRET_CONTENT_PATTERNS:
        cleaned = pat.sub("<REDACTED>", cleaned)
    return cleaned


def is_secret_filename(path: Path) -> bool:
    """Return True if the filename matches known secret/token/key patterns."""
    name = path.name
    return any(pat.search(name) for pat in SECRET_FILENAME_PATTERNS)


def has_secret_content(path: Path) -> bool:
    """Return True if a file contains private keys or raw API tokens."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    if any(pat.search(content) for pat in SECRET_CONTENT_PATTERNS):
        return True
    if INLINE_SECRET_ENV_RE.search(content):
        return True
    return False


def collect_system_metadata(now: datetime | None = None) -> dict[str, Any]:
    """Gather host, operating system, and runtime metadata."""
    now = now or datetime.now(timezone.utc)
    os_pretty = platform.platform()
    os_release_path = Path("/etc/os-release")
    if os_release_path.exists():
        for line in os_release_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("PRETTY_NAME="):
                os_pretty = line.partition("=")[2].strip().strip('"')
                break

    device_model = None
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        try:
            device_model = model_path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="ignore").strip()
        except OSError:
            device_model = None

    var_www_html = Path("/var/www/html")
    webapps_html = DEFAULT_WEBAPPS_DIR / "html"
    webapps_html_target = None
    if webapps_html.exists() or webapps_html.is_symlink():
        try:
            webapps_html_target = str(webapps_html.resolve())
        except OSError:
            webapps_html_target = None

    runtimes: dict[str, str | None] = {}
    for tool, cmd in (
        ("uv", [str(HOME_DIR / ".local/bin/uv"), "--version"]),
        ("bun", [str(HOME_DIR / ".bun/bin/bun"), "--version"]),
        ("node", ["node", "--version"]),
        ("cargo", [str(HOME_DIR / ".cargo/bin/cargo"), "--version"]),
        ("fish", ["fish", "--version"]),
        ("nginx", ["/usr/sbin/nginx", "-v"]),
        ("git", ["git", "--version"]),
        ("gh", ["gh", "--version"]),
    ):
        binary = cmd[0]
        if "/" not in binary:
            resolved = shutil.which(binary)
            if not resolved:
                runtimes[tool] = None
                continue
            cmd = [resolved, *cmd[1:]]
        elif not Path(binary).exists():
            resolved = shutil.which(Path(binary).name)
            if not resolved:
                runtimes[tool] = None
                continue
            cmd = [resolved, *cmd[1:]]
        rc, out, err = _run_cmd(cmd, timeout=5)
        combined = (out or err).splitlines()
        runtimes[tool] = combined[0].strip() if combined and rc == 0 else (combined[0].strip() if combined else None)

    return {
        "generated_at": now.isoformat(),
        "date": now.strftime("%Y%m%d"),
        "hostname": socket.gethostname(),
        "device_model": device_model,
        "os": os_pretty,
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "user": os.environ.get("USER") or HOME_DIR.name,
        "home_dir": str(HOME_DIR),
        "webapps_html_symlink": {
            "path": str(webapps_html),
            "is_symlink": webapps_html.is_symlink(),
            "target": webapps_html_target,
        },
        "var_www_html_exists": var_www_html.exists(),
        "runtimes": runtimes,
    }


def _parse_exec_start(raw: str) -> str | None:
    """Extract a readable command line from systemd's ExecStart show format."""
    if not raw:
        return None
    argv_match = re.search(r"argv\[\]=([^;]+)", raw)
    if argv_match:
        return sanitize_text(argv_match.group(1).strip())
    path_match = re.search(r"path=([^;]+)", raw)
    if path_match:
        return sanitize_text(path_match.group(1).strip())
    return sanitize_text(raw.strip())


def _parse_env_files(raw: str) -> list[str]:
    """Extract file paths from systemd's EnvironmentFiles show property."""
    if not raw:
        return []
    paths: list[str] = []
    for part in raw.split():
        if part.startswith("("):
            continue
        cleaned = part.lstrip("-")
        if cleaned.startswith("/"):
            paths.append(cleaned)
    return paths


def _collect_scope_units(scope: str) -> list[dict[str, Any]]:
    """Collect running and enabled systemd services and timers for a given scope ('system' or 'user')."""
    base_cmd = ["systemctl"] if scope == "system" else ["systemctl", "--user"]

    unit_file_states: dict[str, str] = {}
    rc1, out1, _ = _run_cmd([*base_cmd, "list-unit-files", "--type=service,timer", "--no-pager", "--no-legend"])
    if rc1 == 0 and out1:
        for line in out1.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                unit_file_states[parts[0]] = parts[1]

    active_units: dict[str, tuple[str, str]] = {}
    rc2, out2, _ = _run_cmd([*base_cmd, "list-units", "--type=service,timer", "--all", "--no-pager", "--no-legend", "--plain"])
    if rc2 == 0 and out2:
        for line in out2.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                unit_name, _load, active_state, sub_state = parts[0], parts[1], parts[2], parts[3]
                active_units[unit_name] = (active_state, sub_state)

    custom_dir = Path("/etc/systemd/system") if scope == "system" else (HOME_DIR / ".config/systemd/user")
    custom_files: set[str] = set()
    if custom_dir.exists():
        for ext in ("*.service", "*.timer"):
            for p in custom_dir.glob(ext):
                if not p.is_symlink():
                    custom_files.add(p.name)

    candidate_names: set[str] = set(custom_files)
    for name, u_state in unit_file_states.items():
        if name.endswith("@.service") or name.endswith("@.timer"):
            continue
        if u_state in ("enabled", "enabled-runtime"):
            candidate_names.add(name)
    for name, (a_state, s_state) in active_units.items():
        if a_state in ("active", "activating", "reloading", "failed") and s_state in ("running", "waiting", "failed", "listening"):
            candidate_names.add(name)

    if not candidate_names:
        return []

    sorted_names = sorted(candidate_names)
    props = "Id,FragmentPath,ActiveState,SubState,UnitFileState,WorkingDirectory,ExecStart,User,EnvironmentFiles,Description"
    rc3, out3, _ = _run_cmd([*base_cmd, "show", f"--property={props}", *sorted_names], timeout=20)

    blocks = out3.split("\n\n") if (rc3 == 0 and out3) else []
    parsed_by_id: dict[str, dict[str, str]] = {}
    for block in blocks:
        info: dict[str, str] = {}
        for line in block.splitlines():
            k, sep, v = line.partition("=")
            if sep:
                info[k.strip()] = v.strip()
        if "Id" in info:
            parsed_by_id[info["Id"]] = info

    results: list[dict[str, Any]] = []
    for name in sorted_names:
        info = parsed_by_id.get(name, {})
        active_state = info.get("ActiveState") or active_units.get(name, ("unknown", "unknown"))[0]
        sub_state = info.get("SubState") or active_units.get(name, ("unknown", "unknown"))[1]
        uf_state = info.get("UnitFileState") or unit_file_states.get(name, "unknown")
        fragment_path = info.get("FragmentPath") or None
        if not fragment_path and name in custom_files:
            fragment_path = str(custom_dir / name)

        is_custom = name in custom_files or bool(
            fragment_path and (
                fragment_path.startswith("/etc/systemd/system/")
                or fragment_path.startswith(str(HOME_DIR / ".config/systemd/user"))
            )
        )
        running = active_state == "active" and sub_state in ("running", "waiting", "listening")
        enabled = uf_state in ("enabled", "enabled-runtime")

        entry: dict[str, Any] = {
            "name": name,
            "scope": scope,
            "unit_file_path": fragment_path,
            "state": active_state,
            "sub_state": sub_state,
            "unit_file_state": uf_state,
            "running": running,
            "enabled": enabled,
            "is_custom_unit": is_custom,
            "description": info.get("Description") or None,
        }
        wd = info.get("WorkingDirectory")
        if wd:
            entry["working_directory"] = wd.lstrip("!")
        exec_start = _parse_exec_start(info.get("ExecStart", ""))
        if exec_start:
            entry["exec_start"] = exec_start
        user = info.get("User")
        if user:
            entry["user"] = user
        env_files = _parse_env_files(info.get("EnvironmentFiles", ""))
        if env_files:
            entry["environment_files"] = env_files

        results.append(entry)

    # Sort custom units first, then by name.
    results.sort(key=lambda item: (0 if item["is_custom_unit"] else 1, item["name"]))
    return results


def collect_systemd_services() -> dict[str, Any]:
    """Collect running and enabled systemd services and timers across system and user scopes."""
    system_units = _collect_scope_units("system")
    user_units = _collect_scope_units("user")
    all_units = system_units + user_units
    custom_units = [u for u in all_units if u["is_custom_unit"]]

    return {
        "summary": {
            "total_captured": len(all_units),
            "system_units": len(system_units),
            "user_units": len(user_units),
            "custom_units": len(custom_units),
            "running_count": sum(1 for u in all_units if u["running"]),
            "enabled_count": sum(1 for u in all_units if u["enabled"]),
        },
        "custom_services_and_timers": custom_units,
        "system_services_and_timers": system_units,
        "user_services_and_timers": user_units,
    }


def parse_services_md(services_md_path: Path = DEFAULT_SERVICES_MD) -> dict[str, Any]:
    """Parse ~/WebApps/services.md without exposing any plain-text passwords."""
    if not services_md_path.exists():
        return {
            "exists": False,
            "path": str(services_md_path),
            "entries": [],
            "stray_table_rows": [],
            "redacted_password_headings": [],
            "referenced_secret_paths": [],
        }

    text = services_md_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    entries: list[dict[str, Any]] = []
    stray_table_rows: list[dict[str, Any]] = []
    redacted_password_headings: list[dict[str, Any]] = []
    referenced_secret_paths: set[str] = set()

    current: dict[str, Any] | None = None

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if line.startswith("## "):
            if current is not None:
                entries.append(current)
            current = {
                "heading": line[3:].strip(),
                "line": idx,
                "service": None,
                "services_mentioned": [],
                "port": None,
                "url": None,
                "location": None,
                "description": None,
                "is_static": False,
                "has_access_password_in_doc": False,
            }
            continue

        # Detect stray markdown table rows like `| mgkform | 8000 | ... |`
        if line.startswith("|") and line.endswith("|") and not re.match(r"^\|\s*[-:]+\s*\|", line):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if cols:
                stray_table_rows.append({"line": idx, "columns": cols})
            continue

        if current is None:
            continue

        # Extract any referenced .htpasswd or .password-store paths
        for ht_match in re.findall(r"(/etc/nginx/\.htpasswd[A-Za-z0-9_.-]*)", line):
            referenced_secret_paths.add(ht_match)
        for pass_match in re.findall(r"(~/\.password-store/[A-Za-z0-9_./-]*|~/\.password-store)", line):
            referenced_secret_paths.add(str(HOME_DIR / pass_match.removeprefix("~/")))

        field_match = re.match(r"^-\s+\*\*([^*]+)\*\*:\s*(.+)$", line)
        if not field_match:
            continue

        key = field_match.group(1).strip()
        val = field_match.group(2).strip()
        key_lower = key.lower()

        if "password" in key_lower or "secret" in key_lower or "token" in key_lower:
            # Never record the secret value; only note its presence and line number.
            if key_lower == "access password":
                current["has_access_password_in_doc"] = True
                redacted_password_headings.append({
                    "heading": current["heading"],
                    "line": idx,
                    "field": key,
                })
            continue

        if key_lower == "service":
            current["service"] = val
            unit_names = re.findall(r"\b([A-Za-z0-9_.-]+\.(?:service|timer))\b", val)
            current["services_mentioned"] = unit_names
            if "none" in val.lower() or "static" in val.lower():
                current["is_static"] = True
        elif key_lower == "port":
            current["port"] = val
        elif key_lower == "url":
            current["url"] = val
        elif key_lower == "location":
            current["location"] = val
        elif key_lower == "description":
            current["description"] = sanitize_text(val)

    if current is not None:
        entries.append(current)

    return {
        "exists": True,
        "path": str(services_md_path),
        "entries": entries,
        "stray_table_rows": stray_table_rows,
        "redacted_password_headings": redacted_password_headings,
        "referenced_secret_paths": sorted(referenced_secret_paths),
    }


def collect_services_md_cross_reference(
    systemd_data: dict[str, Any],
    services_md_path: Path = DEFAULT_SERVICES_MD,
) -> dict[str, Any]:
    """Cross-reference ~/WebApps/services.md with live systemd units and filesystem paths."""
    parsed = parse_services_md(services_md_path)
    all_units = (
        systemd_data.get("system_services_and_timers", [])
        + systemd_data.get("user_services_and_timers", [])
    )
    units_by_name = {u["name"]: u for u in all_units}

    documented_unit_names: set[str] = set()
    documented_entries: list[dict[str, Any]] = []
    documented_but_missing_units: list[str] = []
    discrepancies: list[str] = []

    for item in parsed["entries"]:
        mentioned = item["services_mentioned"]
        for u_name in mentioned:
            documented_unit_names.add(u_name)

        matched_units: list[dict[str, Any]] = []
        for u_name in mentioned:
            u = units_by_name.get(u_name)
            if u:
                matched_units.append({
                    "name": u["name"],
                    "scope": u["scope"],
                    "state": u["state"],
                    "sub_state": u["sub_state"],
                    "unit_file_state": u["unit_file_state"],
                    "unit_file_path": u["unit_file_path"],
                    "working_directory": u.get("working_directory"),
                    "exec_start": u.get("exec_start"),
                })
            else:
                documented_but_missing_units.append(u_name)
                discrepancies.append(
                    f"Service '{u_name}' under heading '{item['heading']}' in services.md has no matching systemd unit."
                )

        # Check filesystem path in Location
        loc_raw = item.get("location")
        loc_path_str: str | None = None
        loc_exists: bool | None = None
        if loc_raw:
            loc_clean = loc_raw.split("(")[0].strip()
            loc_path_str = loc_clean
            loc_path = Path(loc_clean).expanduser()
            loc_exists = loc_path.exists()
            if not loc_exists:
                discrepancies.append(
                    f"Heading '{item['heading']}' documents Location '{loc_clean}', which does not exist on disk."
                )
            for mu in matched_units:
                wd = mu.get("working_directory")
                exec_st = mu.get("exec_start") or ""
                if wd and loc_exists:
                    wd_real = Path(wd).resolve()
                    loc_real = loc_path.resolve()
                    if loc_real.is_file():
                        loc_real = loc_real.parent
                    # User services default WorkingDirectory to HOME_DIR; check exec_start if so.
                    if wd_real == HOME_DIR.resolve() and str(loc_real) in exec_st:
                        continue
                    if wd_real != loc_real and loc_real not in wd_real.parents and wd_real not in loc_real.parents:
                        discrepancies.append(
                            f"Unit '{mu['name']}' WorkingDirectory is '{wd}' but services.md lists '{loc_clean}'."
                        )

        documented_entries.append({
            "heading": item["heading"],
            "line": item["line"],
            "service_field": item["service"],
            "is_static": item["is_static"],
            "port": item["port"],
            "url": item["url"],
            "documented_location": loc_path_str,
            "location_exists": loc_exists,
            "description": item["description"],
            "has_access_password_in_doc": item["has_access_password_in_doc"],
            "matched_systemd_units": matched_units,
        })

    for row in parsed["stray_table_rows"]:
        cols = row["columns"]
        discrepancies.append(
            f"Line {row['line']} of services.md contains an unheaded markdown table row for '{cols[0]}' instead of a standard section."
        )

    custom_units = systemd_data.get("custom_services_and_timers", [])
    undocumented_custom_services: list[dict[str, Any]] = []
    for cu in custom_units:
        if cu["name"] not in documented_unit_names:
            undocumented_custom_services.append({
                "name": cu["name"],
                "scope": cu["scope"],
                "state": cu["state"],
                "unit_file_state": cu["unit_file_state"],
                "unit_file_path": cu["unit_file_path"],
                "working_directory": cu.get("working_directory"),
                "exec_start": cu.get("exec_start"),
            })
            discrepancies.append(
                f"Custom unit '{cu['name']}' ({cu['state']}, {cu['unit_file_state']}) at '{cu['unit_file_path']}' is not documented as a section in ~/WebApps/services.md."
            )

    return {
        "services_md_path": parsed["path"],
        "services_md_exists": parsed["exists"],
        "documented_count": len(documented_entries),
        "undocumented_custom_count": len(undocumented_custom_services),
        "documented_entries": documented_entries,
        "undocumented_custom_services": undocumented_custom_services,
        "documented_but_missing_units": sorted(set(documented_but_missing_units)),
        "stray_table_rows": parsed["stray_table_rows"],
        "redacted_password_fields": parsed["redacted_password_headings"],
        "referenced_secret_paths": parsed["referenced_secret_paths"],
        "discrepancies": discrepancies,
    }


def _parse_cron_lines(text: str, has_user_field: bool = False) -> list[dict[str, Any]]:
    """Parse crontab text into structured entries, keeping comments associated with jobs."""
    entries: list[dict[str, Any]] = []
    pending_comments: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            pending_comments.clear()
            continue
        if line.startswith("#"):
            pending_comments.append(line.lstrip("#").strip())
            continue
        # Environment variable assignment inside crontab (e.g. SHELL=/bin/sh)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            entries.append({
                "type": "env",
                "raw": sanitize_text(line),
            })
            pending_comments.clear()
            continue

        if line.startswith("@"):
            parts = line.split(None, 2 if has_user_field else 1)
            if has_user_field and len(parts) == 3:
                entry: dict[str, Any] = {
                    "type": "job",
                    "schedule": parts[0],
                    "user": parts[1],
                    "command": sanitize_text(parts[2]),
                }
            elif len(parts) >= 2:
                entry = {
                    "type": "job",
                    "schedule": parts[0],
                    "command": sanitize_text(parts[1]),
                }
            else:
                entry = {"type": "raw", "raw": sanitize_text(line)}
        else:
            parts = line.split(None, 6 if has_user_field else 5)
            if has_user_field and len(parts) >= 7:
                entry = {
                    "type": "job",
                    "schedule": " ".join(parts[:5]),
                    "user": parts[5],
                    "command": sanitize_text(parts[6]),
                }
            elif not has_user_field and len(parts) >= 6:
                entry = {
                    "type": "job",
                    "schedule": " ".join(parts[:5]),
                    "command": sanitize_text(parts[5]),
                }
            else:
                entry = {"type": "raw", "raw": sanitize_text(line)}

        if pending_comments:
            entry["comments"] = list(pending_comments)
            pending_comments.clear()
        entries.append(entry)

    return entries


def collect_cron_entries() -> dict[str, Any]:
    """Collect user crontab, /etc/crontab, /etc/cron.d, and periodic cron directories."""
    rc, user_out, _ = _run_cmd(["crontab", "-l"])
    user_entries = _parse_cron_lines(user_out, has_user_field=False) if rc == 0 and user_out else []

    etc_crontab_path = Path("/etc/crontab")
    system_entries: list[dict[str, Any]] = []
    if etc_crontab_path.exists():
        try:
            system_entries = _parse_cron_lines(
                etc_crontab_path.read_text(encoding="utf-8", errors="ignore"),
                has_user_field=True,
            )
        except OSError:
            system_entries = []

    cron_d: list[dict[str, Any]] = []
    cron_d_dir = Path("/etc/cron.d")
    if cron_d_dir.exists():
        for p in sorted(cron_d_dir.iterdir()):
            if p.name.startswith(".") or not p.is_file():
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                cron_d.append({
                    "name": p.name,
                    "path": str(p),
                    "entries": _parse_cron_lines(content, has_user_field=True),
                })
            except OSError:
                cron_d.append({"name": p.name, "path": str(p), "entries": []})

    periodic_dirs: dict[str, list[str]] = {}
    for period in ("hourly", "daily", "weekly", "monthly", "yearly"):
        d = Path(f"/etc/cron.{period}")
        if d.exists():
            periodic_dirs[f"cron.{period}"] = sorted(
                str(p) for p in d.iterdir() if not p.name.startswith(".") and p.is_file()
            )

    return {
        "user_crontab": {
            "user": os.environ.get("USER") or HOME_DIR.name,
            "entries": user_entries,
        },
        "system_crontab": {
            "path": str(etc_crontab_path),
            "entries": system_entries,
        },
        "cron_d": cron_d,
        "periodic_scripts": periodic_dirs,
    }


def _strip_nested_blocks(block: str) -> str:
    """Remove nested `{ ... }` sub-blocks from an nginx location block before directive matching."""
    out: list[str] = []
    depth = 0
    for ch in block:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _extract_nginx_locations(content: str) -> list[dict[str, Any]]:
    """Parse top-level and nested location blocks from an nginx configuration file."""
    locations: list[dict[str, Any]] = []
    loc_header_re = re.compile(r"location\s+([^{\n]+)\{")

    for match in loc_header_re.finditer(content):
        route = match.group(1).strip()
        start_idx = match.end()
        depth = 1
        idx = start_idx
        while idx < len(content) and depth > 0:
            ch = content[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            idx += 1
        raw_block = content[start_idx : idx - 1]
        block = _strip_nested_blocks(raw_block)

        proxy_match = re.search(r"proxy_pass\s+([^;]+);", block)
        alias_match = re.search(r"alias\s+([^;]+);", block)
        root_match = re.search(r"root\s+([^;]+);", block)
        return_match = re.search(r"return\s+([^;]+);", block)
        auth_file_match = re.search(r"auth_basic_user_file\s+([^;]+);", block)
        includes = sorted(set(m.strip() for m in re.findall(r"include\s+([^;]+);", block)))
        deny_all = bool(re.search(r"\bdeny\s+all\s*;", block))

        if proxy_match:
            loc_type = "proxy"
        elif alias_match:
            loc_type = "static_alias"
        elif root_match:
            loc_type = "static_root"
        elif deny_all:
            loc_type = "deny"
        elif return_match:
            loc_type = "redirect_or_return"
        else:
            loc_type = "try_files"

        loc_entry: dict[str, Any] = {
            "route": route,
            "type": loc_type,
        }
        if proxy_match:
            loc_entry["proxy_pass"] = proxy_match.group(1).strip()
        if alias_match:
            loc_entry["alias"] = alias_match.group(1).strip()
        if root_match:
            loc_entry["root"] = root_match.group(1).strip()
        if return_match:
            loc_entry["return"] = return_match.group(1).strip()
        if auth_file_match:
            loc_entry["auth_basic_user_file"] = auth_file_match.group(1).strip()
        if includes:
            loc_entry["includes"] = includes

        locations.append(loc_entry)

    return locations


def collect_nginx_sites(nginx_dir: Path = Path("/etc/nginx")) -> dict[str, Any]:
    """Capture nginx sites-enabled symlinks, targets, routes, snippets, and auth file paths."""
    sites_enabled_dir = nginx_dir / "sites-enabled"
    snippets_dir = nginx_dir / "snippets"

    sites: list[dict[str, Any]] = []
    all_auth_files: set[str] = set()
    all_ssl_files: set[str] = set()

    if sites_enabled_dir.exists():
        for entry in sorted(sites_enabled_dir.iterdir()):
            if entry.name.startswith("."):
                continue
            target_path = None
            if entry.is_symlink():
                try:
                    target_path = str(entry.resolve())
                except OSError:
                    target_path = str(os.readlink(entry))
            else:
                target_path = str(entry)

            try:
                raw_content = entry.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                raw_content = ""

            # Strip full-line comments for directive extraction
            active_lines = [
                ln for ln in raw_content.splitlines() if not ln.strip().startswith("#")
            ]
            cleaned = "\n".join(active_lines)

            server_names: list[str] = []
            for sn_match in re.findall(r"server_name\s+([^;]+);", cleaned):
                for host in sn_match.split():
                    if host not in server_names:
                        server_names.append(host)

            listen_directives = [
                m.strip() for m in re.findall(r"listen\s+([^;]+);", cleaned)
            ]
            roots = sorted(set(m.strip() for m in re.findall(r"\broot\s+([^;]+);", cleaned)))
            includes = sorted(set(m.strip() for m in re.findall(r"\binclude\s+([^;]+);", cleaned)))
            auth_files = sorted(
                set(m.strip() for m in re.findall(r"auth_basic_user_file\s+([^;]+);", cleaned))
            )
            ssl_certs = sorted(
                set(
                    m.strip()
                    for m in re.findall(
                        r"ssl_(?:certificate|certificate_key|dhparam)\s+([^;]+);",
                        cleaned,
                    )
                )
            )
            for af in auth_files:
                all_auth_files.add(af)
            for sc in ssl_certs:
                all_ssl_files.add(sc)

            locations = _extract_nginx_locations(cleaned)

            sites.append({
                "name": entry.name,
                "symlink_path": str(entry),
                "target_path": target_path,
                "is_symlink": entry.is_symlink(),
                "server_names": server_names,
                "listen_directives": listen_directives,
                "root_paths": roots,
                "includes": includes,
                "ssl_certificate_paths": ssl_certs,
                "auth_basic_user_files": auth_files,
                "location_count": len(locations),
                "locations": locations,
            })

    snippets: list[dict[str, Any]] = []
    if snippets_dir.exists():
        for snip in sorted(snippets_dir.iterdir()):
            if snip.name.startswith(".") or not snip.is_file():
                continue
            try:
                snip_text = snip.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                snip_text = ""
            snip_auth = sorted(
                set(m.strip() for m in re.findall(r"auth_basic_user_file\s+([^;]+);", snip_text))
            )
            for af in snip_auth:
                all_auth_files.add(af)
            gate_files = sorted(
                set(m.strip() for m in re.findall(r"-f\s+([^\s)]+)", snip_text))
            )
            snippets.append({
                "name": snip.name,
                "path": str(snip),
                "auth_basic_user_files": snip_auth,
                "conditional_files": gate_files,
            })

    return {
        "sites_enabled_dir": str(sites_enabled_dir),
        "sites_enabled": sites,
        "snippets": snippets,
        "referenced_htpasswd_paths": sorted(all_auth_files),
        "referenced_ssl_paths": sorted(all_ssl_files),
    }


def _inspect_git_repo(repo_dir: Path) -> dict[str, Any]:
    """Inspect a single git repository for remotes, branch, dirty status, and latest commit."""
    git_entry = repo_dir / ".git"
    is_worktree = git_entry.is_file() or ".worktrees" in repo_dir.parts
    is_backup_copy = "backups" in repo_dir.parts

    # Remotes
    remotes: dict[str, str] = {}
    rc_rem, out_rem, _ = _run_cmd(["git", "-C", str(repo_dir), "remote", "-v"])
    if rc_rem == 0 and out_rem:
        for line in out_rem.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in remotes:
                remotes[parts[0]] = sanitize_text(parts[1])

    primary_remote = remotes.get("origin") or (next(iter(remotes.values())) if remotes else None)

    # Branch
    rc_br, branch, _ = _run_cmd(["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"])
    if rc_br != 0 or not branch:
        rc_sym, sym_branch, _ = _run_cmd(["git", "-C", str(repo_dir), "symbolic-ref", "--short", "HEAD"])
        branch = sym_branch if rc_sym == 0 and sym_branch else "HEAD (unborn or detached)"

    # Uncommitted changes
    rc_st, status_out, _ = _run_cmd(["git", "-C", str(repo_dir), "status", "--porcelain"])
    status_lines = [ln for ln in status_out.splitlines() if ln.strip()] if rc_st == 0 and status_out else []
    uncommitted_changes = len(status_lines) > 0
    untracked_count = sum(1 for ln in status_lines if ln.startswith("??"))
    modified_or_staged_count = len(status_lines) - untracked_count

    # Latest commit
    rc_log, log_out, _ = _run_cmd(
        ["git", "-C", str(repo_dir), "log", "-1", "--format=%H%n%h%n%cI%n%an%n%s"]
    )
    latest_commit: dict[str, str | None] | None = None
    if rc_log == 0 and log_out:
        log_lines = log_out.splitlines()
        if len(log_lines) >= 5:
            latest_commit = {
                "hash": log_lines[0].strip(),
                "short_hash": log_lines[1].strip(),
                "date": log_lines[2].strip(),
                "author": log_lines[3].strip(),
                "subject": sanitize_text(log_lines[4].strip()),
            }

    return {
        "name": repo_dir.name,
        "path": str(repo_dir),
        "remote_url": primary_remote,
        "remotes": remotes,
        "branch": branch,
        "uncommitted_changes": uncommitted_changes,
        "uncommitted_summary": {
            "modified_or_staged": modified_or_staged_count,
            "untracked": untracked_count,
            "total": len(status_lines),
        },
        "latest_commit": latest_commit,
        "is_worktree": is_worktree,
        "is_backup_copy": is_backup_copy,
    }


def collect_git_projects(
    roots: list[Path] | None = None,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Find and inspect every Git repository under ~/WebApps and ~/jobrunner."""
    if roots is None:
        roots = [DEFAULT_WEBAPPS_DIR, DEFAULT_JOBRUNNER_DIR]

    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "target"}
    discovered_paths: set[Path] = set()

    # Expand top-level symlinked directories (such as ~/WebApps/html -> /var/www/html)
    walk_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        r_res = root.resolve()
        if r_res not in seen_roots:
            seen_roots.add(r_res)
            walk_roots.append(r_res)
        try:
            for child in sorted(root.iterdir()):
                if child.is_symlink() and child.is_dir():
                    c_res = child.resolve()
                    if c_res not in seen_roots:
                        seen_roots.add(c_res)
                        walk_roots.append(c_res)
        except OSError:
            pass

    for root_resolved in walk_roots:
        for current_root, dirs, files in os.walk(root_resolved, topdown=True, followlinks=False):
            curr_path = Path(current_root)
            rel_parts = curr_path.relative_to(root_resolved).parts
            if len(rel_parts) > max_depth:
                dirs[:] = []
                continue

            if ".git" in dirs or ".git" in files:
                discovered_paths.add(curr_path.resolve())

            # Prune heavy or internal directories, including .git itself
            dirs[:] = [
                d for d in dirs
                if d != ".git" and d not in skip_dirs
            ]

    projects = [_inspect_git_repo(p) for p in sorted(discovered_paths)]
    primary_projects = [
        p for p in projects if not p["is_worktree"] and not p["is_backup_copy"]
    ]

    return {
        "summary": {
            "total_repositories": len(projects),
            "primary_repositories": len(primary_projects),
            "worktrees": sum(1 for p in projects if p["is_worktree"]),
            "backup_copies": sum(1 for p in projects if p["is_backup_copy"]),
            "with_uncommitted_changes": sum(1 for p in projects if p["uncommitted_changes"]),
            "without_remote": sum(1 for p in projects if not p["remote_url"]),
        },
        "projects": projects,
    }


def collect_secret_paths(
    roots: list[Path] | None = None,
    nginx_data: dict[str, Any] | None = None,
    services_xref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """List paths (and ONLY paths) of secrets, keys, tokens, and password files required for restoration."""
    if roots is None:
        roots = [DEFAULT_WEBAPPS_DIR, DEFAULT_JOBRUNNER_DIR]

    def _path_record(p: Path) -> dict[str, Any]:
        try:
            exists: bool | str = p.exists() or p.is_symlink()
            kind = "directory" if (exists and p.is_dir()) else "file"
        except PermissionError:
            exists = "permission_restricted"
            kind = "file"
        except OSError:
            exists = False
            kind = "file"
        return {
            "path": str(p),
            "exists": exists,
            "type": kind,
        }

    ssh_dir = HOME_DIR / ".ssh"
    ssh_paths: list[Path] = []
    if ssh_dir.exists():
        for p in sorted(ssh_dir.iterdir()):
            if p.name in ("config", "known_hosts", "known_hosts.old"):
                continue
            ssh_paths.append(p)
    else:
        ssh_paths = [
            ssh_dir / "id_ed25519_personal",
            ssh_dir / "id_ed25519_wta",
            ssh_dir / "authorized_keys",
        ]

    gpg_and_pass_candidates = [
        HOME_DIR / ".gnupg",
        HOME_DIR / ".password-store",
        HOME_DIR / ".password-store/.gpg-id",
        HOME_DIR / ".password-store/gmail-cleaner",
        HOME_DIR / ".password-store/secret_service",
    ]

    htpasswd_paths: set[Path] = set()
    nginx_etc = Path("/etc/nginx")
    if nginx_etc.exists():
        for p in nginx_etc.glob(".htpasswd*"):
            htpasswd_paths.add(p)
    if nginx_data:
        for p_str in nginx_data.get("referenced_htpasswd_paths", []):
            htpasswd_paths.add(Path(p_str))
    if services_xref:
        for p_str in services_xref.get("referenced_secret_paths", []):
            if ".htpasswd" in p_str:
                htpasswd_paths.add(Path(p_str))

    tls_paths: set[Path] = {
        Path("/etc/letsencrypt/live/architools.duckdns.org/fullchain.pem"),
        Path("/etc/letsencrypt/live/architools.duckdns.org/privkey.pem"),
        Path("/etc/letsencrypt/ssl-dhparams.pem"),
    }
    if nginx_data:
        for p_str in nginx_data.get("referenced_ssl_paths", []):
            tls_paths.add(Path(p_str))

    cli_cred_candidates = [
        HOME_DIR / ".claude/.credentials.json",
        HOME_DIR / ".config/gh/hosts.yml",
        HOME_DIR / ".supabase/access-token",
        HOME_DIR / ".cli-m365-all-connections.json",
        HOME_DIR / ".cli-m365-connection.json",
        HOME_DIR / ".cli-m365-msal.json",
        HOME_DIR / "duckdns/duck.sh",
    ]

    # Discover .env / .env.local files under roots
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}
    env_files: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if re.match(r"^\.env($|\.(?!example$|sample$|template$))", fname, re.IGNORECASE):
                    env_files.add(Path(current_root) / fname)

    redacted_doc_fields = (
        services_xref.get("redacted_password_fields", []) if services_xref else []
    )

    return {
        "policy": "Secret, token, key, and password contents are strictly excluded; only file paths and existence flags are recorded.",
        "ssh_keys_and_auth": [_path_record(p) for p in ssh_paths],
        "gpg_and_password_store": [_path_record(p) for p in gpg_and_pass_candidates if p.exists() or p in gpg_and_pass_candidates[:2]],
        "nginx_htpasswd_files": [_path_record(p) for p in sorted(htpasswd_paths)],
        "tls_certificates": [_path_record(p) for p in sorted(tls_paths)],
        "cli_and_agent_credentials": [_path_record(p) for p in cli_cred_candidates if p.exists()],
        "project_env_files": [_path_record(p) for p in sorted(env_files)],
        "redacted_documentation_secrets": {
            "source_file": str(DEFAULT_SERVICES_MD),
            "omitted_fields": redacted_doc_fields,
        },
    }


def copy_dotfiles(
    output_dir: Path,
    home_dir: Path = HOME_DIR,
    dotfile_relpaths: tuple[str, ...] = DEFAULT_DOTFILES,
) -> dict[str, Any]:
    """Copy key non-secret dotfiles into output_dir / 'dotfiles' preserving relative structure."""
    dest_root = output_dir / "dotfiles"
    dest_root.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    skipped_missing: list[str] = []
    skipped_secret: list[dict[str, str]] = []

    def _copy_single_file(src_file: Path, rel_str: str) -> None:
        if is_secret_filename(src_file):
            skipped_secret.append({"path": str(src_file), "reason": "secret_filename_pattern"})
            return
        if has_secret_content(src_file):
            skipped_secret.append({"path": str(src_file), "reason": "secret_content_pattern"})
            return
        dst_file = dest_root / rel_str
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied.append({
            "source": str(src_file),
            "relative_path": rel_str,
            "destination": str(dst_file),
        })

    for rel in dotfile_relpaths:
        src = home_dir / rel
        if not src.exists():
            skipped_missing.append(str(src))
            continue

        if src.is_file():
            _copy_single_file(src, rel)
        elif src.is_dir():
            for root_str, dirs, files in os.walk(src, topdown=True, followlinks=False):
                # Do not copy nested .git repositories or caches inside .config directories
                dirs[:] = [
                    d for d in sorted(dirs)
                    if d not in {".git", "__pycache__", ".venv", "node_modules", "cache"}
                ]
                for fname in sorted(files):
                    if fname.endswith((".bak", "~", ".swp", ".swo")):
                        continue
                    f_src = Path(root_str) / fname
                    f_rel = str(f_src.relative_to(home_dir))
                    _copy_single_file(f_src, f_rel)

    return {
        "enabled": True,
        "destination_dir": str(dest_root),
        "copied_count": len(copied),
        "copied_files": copied,
        "skipped_missing": skipped_missing,
        "skipped_secret": skipped_secret,
    }


def build_restore_notes() -> dict[str, Any]:
    """Build structured UK English restoration notes for the manifest."""
    return {
        "overview": (
            "Step-by-step restoration sequence for rebuilding this Raspberry Pi from "
            "pi-YYYYMMDD.json (referred to as pi-date.json in notes) and the archived dotfiles."
        ),
        "steps": [
            {
                "order": 1,
                "title": "Base Operating System and Core Packages",
                "commands": [
                    "sudo apt-get update && sudo apt-get upgrade -y",
                    "sudo apt-get install -y git nginx certbot python3-certbot-nginx fish tmux vim pass gnupg sqlite3 imagemagick build-essential curl",
                    "curl -LsSf https://astral.sh/uv/install.sh | sh",
                    "curl -fsSL https://bun.sh/install | bash",
                ],
                "notes": [
                    "Set Fish (/usr/bin/fish) as the default shell or launch via tmux (.tmux.conf sets default-shell to /usr/bin/fish).",
                    "Install OpenJDK 21 (openjdk-21-jre-headless) if restoring the standalone XWiki service.",
                ],
            },
            {
                "order": 2,
                "title": "Restore Secrets, Keys, and Credentials Out-of-Band",
                "commands": [
                    "mkdir -p ~/.ssh && chmod 700 ~/.ssh",
                    "chmod 600 ~/.ssh/id_ed25519_personal ~/.ssh/id_ed25519_wta ~/.ssh/authorized_keys",
                    "gpg --import <path-to-backed-up-gpg-secret-key.asc>",
                ],
                "notes": [
                    "Restore SSH keys (~/.ssh/id_ed25519_personal and ~/.ssh/id_ed25519_wta) and ~/.ssh/config so multi-account Git remotes (github.com-personal and github.com-wta) authenticate automatically.",
                    "Restore ~/.gnupg and ~/.password-store (used by pass-secret-service and gmail-cleaner).",
                    "Re-authenticate CLI tools: `gh auth login`, `claude auth`, and restore ~/.supabase/access-token and ~/duckdns/duck.sh.",
                    "Recreate nginx basic-auth files listed under secret_paths.nginx_htpasswd_files using `sudo htpasswd -c /etc/nginx/.htpasswd-<name> <user>`.",
                ],
            },
            {
                "order": 3,
                "title": "Restore Non-Secret Dotfiles",
                "commands": [
                    "cp -a ./output/dotfiles/. ~/",
                ],
                "notes": [
                    "Restores .bashrc, .profile, .zshrc, .gitconfig, .gitconfig-personal, .gitconfig-wta, .tmux.conf, .vimrc, .ssh/config, and ~/.config/{fish,nvim,git,systemd}.",
                    "Alternatively, clone git@github.com-personal:Al4st41r/dotfiles.git and copy updated configurations.",
                ],
            },
            {
                "order": 4,
                "title": "Create Directory Structure and Web Root Symlink",
                "commands": [
                    "mkdir -p ~/WebApps ~/WebApps/Tools ~/WebApps/html ~/jobrunner",
                    "sudo rm -rf /var/www/html && sudo ln -s /home/pi/WebApps/html /var/www/html",
                ],
                "notes": [
                    "All static web assets in ~/WebApps/html/ become immediately accessible under /var/www/html/ via this symlink.",
                ],
            },
            {
                "order": 5,
                "title": "Clone Git Projects and Rebuild Environments",
                "commands": [
                    "# Iterate over git_projects.projects in pi-date.json:",
                    "# git clone <remote_url> <path> && git -C <path> checkout <branch>",
                ],
                "notes": [
                    "Use the remote_url recorded in git_projects.projects (which preserves the github.com-wta and github.com-personal SSH host aliases).",
                    "For Python projects with pyproject.toml, run `uv sync` (or `uv venv && uv pip install -r requirements.txt`).",
                    "For JavaScript/TypeScript projects with package.json, run `bun install` and `bun run build` where a dist/ directory is served by nginx.",
                    "Recreate each project's .env or .env.local file listed under secret_paths.project_env_files.",
                ],
            },
            {
                "order": 6,
                "title": "Restore Systemd Services and Timers",
                "commands": [
                    "sudo systemctl daemon-reload",
                    "# For each unit in systemd_services.custom_services_and_timers (scope == 'system'):",
                    "# sudo systemctl enable --now <name>",
                    "systemctl --user daemon-reload",
                    "systemctl --user enable --now pass-secret-service.service",
                ],
                "notes": [
                    "Inspect services_md_cross_reference.discrepancies in pi-date.json to review undocumented custom services (such as christmas-card-crm, exceltool, ifc2cobie, mgkform, pricetracker, uww-generator, and webpodcasts) before enabling them.",
                ],
            },
            {
                "order": 7,
                "title": "Restore Nginx Configuration and TLS Certificates",
                "commands": [
                    "sudo ln -sf /etc/nginx/sites-available/architools.conf /etc/nginx/sites-enabled/architools.conf",
                    "sudo certbot --nginx -d architools.duckdns.org -d architools.mooo.com -d architools.drawingtable.net",
                    "sudo nginx -t && sudo nginx -s reload",
                ],
                "notes": [
                    "Ensure /etc/nginx/snippets/biogenic-gate.conf and all /etc/nginx/.htpasswd-* files are in place before running `sudo nginx -t`.",
                ],
            },
            {
                "order": 8,
                "title": "Restore Cron Entries",
                "commands": [
                    "crontab -e  # Restore entries from cron.user_crontab.entries in pi-date.json",
                ],
                "notes": [
                    "Restores the Playbook database backup (02:00 daily), jobrunner 15-minute scheduler, and AOwiki daily ingestion/lint jobs.",
                ],
            },
        ],
    }


def generate_manifest(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    include_dotfiles: bool = False,
    now: datetime | None = None,
    webapps_dir: Path = DEFAULT_WEBAPPS_DIR,
    jobrunner_dir: Path = DEFAULT_JOBRUNNER_DIR,
    services_md_path: Path = DEFAULT_SERVICES_MD,
    nginx_dir: Path = Path("/etc/nginx"),
    home_dir: Path = HOME_DIR,
) -> tuple[Path, dict[str, Any]]:
    """Collect all restoration data, write pi-YYYYMMDD.json (and pi-date.json), and return (path, manifest)."""
    now = now or datetime.now(timezone.utc)
    meta = collect_system_metadata(now=now)
    systemd_data = collect_systemd_services()
    services_xref = collect_services_md_cross_reference(systemd_data, services_md_path=services_md_path)
    cron_data = collect_cron_entries()
    nginx_data = collect_nginx_sites(nginx_dir=nginx_dir)
    git_data = collect_git_projects(roots=[webapps_dir, jobrunner_dir])
    secret_paths = collect_secret_paths(
        roots=[webapps_dir, jobrunner_dir],
        nginx_data=nginx_data,
        services_xref=services_xref,
    )
    restore_notes = build_restore_notes()

    dotfiles_result: dict[str, Any] = {
        "enabled": False,
        "note": "Run with --dotfiles to copy non-secret dotfiles into ./output/dotfiles/.",
    }
    if include_dotfiles:
        dotfiles_result = copy_dotfiles(output_dir=output_dir, home_dir=home_dir)

    manifest: dict[str, Any] = {
        "metadata": meta,
        "systemd_services": systemd_data,
        "services_md_cross_reference": services_xref,
        "cron": cron_data,
        "nginx": nginx_data,
        "git_projects": git_data,
        "secret_paths": secret_paths,
        "dotfiles": dotfiles_result,
        "restore-notes": restore_notes,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    dated_filename = f"pi-{meta['date']}.json"
    dated_path = output_dir / dated_filename
    alias_path = output_dir / "pi-date.json"

    serialized = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    dated_path.write_text(serialized, encoding="utf-8")
    alias_path.write_text(serialized, encoding="utf-8")

    return dated_path, manifest


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="pi-backup",
        description=(
            "Generate a Raspberry Pi restoration manifest (pi-YYYYMMDD.json and pi-date.json) "
            "in ./output/ and optionally archive non-secret dotfiles."
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for pi-YYYYMMDD.json and dotfiles (default: ./output).",
    )
    parser.add_argument(
        "--dotfiles",
        action="store_true",
        help="Copy key non-secret dotfiles into <output-dir>/dotfiles/.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override date stamp in YYYYMMDD format (defaults to current UTC date).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if args.date:
        if not re.match(r"^\d{8}$", args.date):
            parser.error("--date must be in YYYYMMDD format.")
        now = datetime.strptime(args.date, "%Y%m%d").replace(tzinfo=timezone.utc)

    dated_path, manifest = generate_manifest(
        output_dir=args.output_dir.resolve(),
        include_dotfiles=args.dotfiles,
        now=now,
    )

    sys_summary = manifest["systemd_services"]["summary"]
    git_summary = manifest["git_projects"]["summary"]
    xref = manifest["services_md_cross_reference"]

    print(f"Wrote manifest: {dated_path}")
    print(f"Wrote alias:    {dated_path.parent / 'pi-date.json'}")
    print(
        f"Systemd units:  {sys_summary['total_captured']} captured "
        f"({sys_summary['custom_units']} custom, {sys_summary['running_count']} running)"
    )
    print(
        f"services.md:    {xref['documented_count']} documented, "
        f"{xref['undocumented_custom_count']} undocumented custom units, "
        f"{len(xref['discrepancies'])} discrepancies noted"
    )
    print(
        f"Git projects:   {git_summary['total_repositories']} total "
        f"({git_summary['with_uncommitted_changes']} with uncommitted changes)"
    )
    if args.dotfiles:
        df = manifest["dotfiles"]
        print(f"Dotfiles:       {df['copied_count']} files copied to {df['destination_dir']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
