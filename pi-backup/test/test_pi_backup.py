"""Tests for the pi-backup manifest generator and dotfile archiver."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import main as pi_backup


def test_sanitize_text_redacts_secrets() -> None:
    raw = (
        "https://user:supersecret@github.com/org/repo.git "
        "SUPABASE_DB_PASSWORD=my_secret_pw "
        "TOKEN='ghp_1234567890abcdefghijklmnopqrstuv'"
    )
    cleaned = pi_backup.sanitize_text(raw)
    assert "supersecret" not in cleaned
    assert "my_secret_pw" not in cleaned
    assert "ghp_1234567890abcdefghijklmnopqrstuv" not in cleaned
    assert "<REDACTED>" in cleaned


def test_is_secret_filename_and_content(tmp_path: Path) -> None:
    assert pi_backup.is_secret_filename(Path(".env"))
    assert pi_backup.is_secret_filename(Path(".env.local"))
    assert not pi_backup.is_secret_filename(Path(".env.example"))
    assert pi_backup.is_secret_filename(Path("id_ed25519_wta"))
    assert pi_backup.is_secret_filename(Path("authorized_keys"))
    assert pi_backup.is_secret_filename(Path(".htpasswd-insights"))
    assert not pi_backup.is_secret_filename(Path(".bashrc"))
    assert not pi_backup.is_secret_filename(Path("config"))

    secret_file = tmp_path / "custom_rc"
    secret_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", encoding="utf-8")
    assert pi_backup.has_secret_content(secret_file)

    safe_file = tmp_path / ".gitconfig"
    safe_file.write_text("[user]\n\tname = Alastair\n", encoding="utf-8")
    assert not pi_backup.has_secret_content(safe_file)


def test_parse_services_md_omits_passwords(tmp_path: Path) -> None:
    md_file = tmp_path / "services.md"
    md_file.write_text(
        "# WebApps Services Registry\n\n"
        "| mgkform | 8000 | Screener | [Link](https://architools.drawingtable.net/mgkform/) |\n\n"
        "## playbook\n"
        "- **Service**: playbook.service\n"
        "- **URL**: https://architools.drawingtable.net/Wiki/Playbook/\n"
        "- **Location**: /home/pi/WebApps/Wiki/Playbook/\n"
        "- **Description**: Wiki Playbook\n"
        "- **Access Password**: SUPER_SECRET_PASS_123\n\n"
        "## biogenic-notes\n"
        "- **Port**: 5061\n"
        "- **URL**: https://architools.drawingtable.net/biogenic-notes/ (`/etc/nginx/.htpasswd-biogenic-notes`)\n"
        "- **Service**: biogenic-notes.service\n"
        "- **Location**: /home/pi/WebApps/BioGenicWorld/app.py\n",
        encoding="utf-8",
    )

    parsed = pi_backup.parse_services_md(md_file)
    dump = json.dumps(parsed)
    assert "SUPER_SECRET_PASS_123" not in dump
    assert parsed["entries"][0]["heading"] == "playbook"
    assert parsed["entries"][0]["has_access_password_in_doc"] is True
    assert len(parsed["redacted_password_headings"]) == 1
    assert "/etc/nginx/.htpasswd-biogenic-notes" in parsed["referenced_secret_paths"]
    assert len(parsed["stray_table_rows"]) == 1


def test_parse_cron_lines() -> None:
    cron_text = (
        "# Playbook DB backup\n"
        "0 2 * * * /home/pi/WebApps/Wiki/Playbook/scripts/backup_db.sh\n"
        "API_TOKEN=secret_value_999\n"
        "@daily root /usr/local/bin/cleanup.sh\n"
    )
    user_entries = pi_backup._parse_cron_lines(cron_text, has_user_field=False)
    assert user_entries[0]["schedule"] == "0 2 * * *"
    assert user_entries[0]["comments"] == ["Playbook DB backup"]
    assert "secret_value_999" not in json.dumps(user_entries)

    sys_entries = pi_backup._parse_cron_lines("@daily root /usr/local/bin/cleanup.sh\n", has_user_field=True)
    assert sys_entries[0]["schedule"] == "@daily"
    assert sys_entries[0]["user"] == "root"
    assert sys_entries[0]["command"] == "/usr/local/bin/cleanup.sh"


def test_extract_nginx_locations_handles_nested_blocks() -> None:
    conf = """
    server {
        location /insights/ {
            location /insights/emails/ {
                alias /var/www/html/insights/emails/;
                auth_basic_user_file /etc/nginx/.htpasswd-insights;
            }
            alias /var/www/html/insights/;
            auth_basic_user_file /etc/nginx/.htpasswd-insights;
        }
        location /simplecarbon/ {
            proxy_pass http://127.0.0.1:5020/;
        }
    }
    """
    locs = pi_backup._extract_nginx_locations(conf)
    by_route = {loc["route"]: loc for loc in locs}
    assert by_route["/insights/"]["alias"] == "/var/www/html/insights/"
    assert by_route["/insights/emails/"]["alias"] == "/var/www/html/insights/emails/"
    assert by_route["/simplecarbon/"]["proxy_pass"] == "http://127.0.0.1:5020/"


def test_collect_git_projects(tmp_path: Path) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com-personal:Al4st41r/sample.git"],
        check=True,
    )
    (repo / "README.md").write_text("# Sample\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Initial commit"], check=True, capture_output=True)

    # Create an untracked file to trigger uncommitted_changes
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    data = pi_backup.collect_git_projects(roots=[tmp_path])
    assert data["summary"]["total_repositories"] == 1
    proj = data["projects"][0]
    assert proj["name"] == "sample-repo"
    assert proj["remote_url"] == "git@github.com-personal:Al4st41r/sample.git"
    assert proj["branch"] == "main"
    assert proj["uncommitted_changes"] is True
    assert proj["latest_commit"]["subject"] == "Initial commit"


def test_copy_dotfiles_filters_secrets_and_backups(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".bashrc").write_text("export PATH=$HOME/.local/bin:$PATH\n", encoding="utf-8")
    (fake_home / ".env").write_text("SECRET_TOKEN=12345\n", encoding="utf-8")

    fish_funcs = fake_home / ".config/fish/functions"
    fish_funcs.mkdir(parents=True)
    (fish_funcs / "greet.fish").write_text("function greet; echo hi; end\n", encoding="utf-8")
    (fish_funcs / "greet.fish.bak").write_text("backup\n", encoding="utf-8")

    out_dir = tmp_path / "output"
    res = pi_backup.copy_dotfiles(
        output_dir=out_dir,
        home_dir=fake_home,
        dotfile_relpaths=(".bashrc", ".env", ".config/fish/functions"),
    )

    copied_rels = {item["relative_path"] for item in res["copied_files"]}
    assert ".bashrc" in copied_rels
    assert ".config/fish/functions/greet.fish" in copied_rels
    assert ".env" not in copied_rels
    assert ".config/fish/functions/greet.fish.bak" not in copied_rels
    assert len(res["skipped_secret"]) == 1


def test_live_manifest_contains_required_sections_and_no_passwords(tmp_path: Path) -> None:
    dated_path, data = pi_backup.generate_manifest(
        output_dir=tmp_path,
        include_dotfiles=True,
        now=datetime(2026, 10, 30, tzinfo=timezone.utc),
    )
    assert dated_path.name == "pi-20261030.json"
    assert dated_path.exists()
    assert (tmp_path / "pi-date.json").exists()
    raw = dated_path.read_text(encoding="utf-8")

    for key in (
        "metadata",
        "systemd_services",
        "services_md_cross_reference",
        "cron",
        "nginx",
        "git_projects",
        "secret_paths",
        "dotfiles",
        "restore-notes",
    ):
        assert key in data, f"Missing top-level section: {key}"

    # Verify plain-text passwords from ~/WebApps/services.md are never present in the JSON output
    assert "WTA2026" not in raw
    assert "Al45t41r" not in raw

