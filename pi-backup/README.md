# Pi Backup and Restoration Manifest (`pi-backup`)

`pi-backup` is a `uv`-managed Python command-line tool that generates `./output/pi-YYYYMMDD.json` (alongside the fixed alias `./output/pi-date.json`) capturing the configuration state required to restore this Raspberry Pi quickly. It also provides a `--dotfiles` mode that copies key non-secret dotfiles into `./output/dotfiles/`.

The tool is read-only with respect to system configuration: it does not install, modify, reload, or restart any services.

## Usage

Run the manifest generator from `/home/pi/WebApps/Tools/pi-backup`:

```bash
# Generate ./output/pi-YYYYMMDD.json and ./output/pi-date.json
uv run python main.py

# Generate the JSON manifest and copy non-secret dotfiles into ./output/dotfiles/
uv run python main.py --dotfiles

# Specify a custom output directory or override the date stamp (YYYYMMDD)
uv run python main.py --output-dir ./output --date 20261030 --dotfiles

# Run the automated test suite
uv run pytest
```

## Captured Manifest Sections

Each generated `pi-YYYYMMDD.json` (and `pi-date.json`) contains the following top-level keys:

- `metadata`: Hostname, Raspberry Pi hardware model, operating system release, kernel version, user, `/home/pi/WebApps/html` -> `/var/www/html` symlink state, and installed toolchain versions (`uv`, `bun`, `node`, `cargo`, `fish`, `nginx`, `git`, `gh`).
- `systemd_services`: Running and enabled systemd services and timers across both `system` and `user` scopes, recording unit name, scope, unit file path, active state, sub-state, unit file state, custom-unit flag, working directory, `ExecStart` command, user, and referenced `EnvironmentFile` paths.
- `services_md_cross_reference`: Cross-reference of `~/WebApps/services.md` against live systemd units and filesystem locations. Reports documented entries, undocumented custom systemd units, stray table rows, and path discrepancies.
- `cron`: User crontab (`crontab -l`), `/etc/crontab`, `/etc/cron.d/*` entries, and scripts installed under `/etc/cron.{hourly,daily,weekly,monthly,yearly}`.
- `nginx`: Every entry in `/etc/nginx/sites-enabled/` (symlink path, resolved target in `/etc/nginx/sites-available/`, `server_name` values, `listen` directives, `root` paths, included snippets, TLS certificate paths, HTTP Basic Auth `.htpasswd` file paths, and parsed `location` blocks) plus `/etc/nginx/snippets/`.
- `git_projects`: Every Git repository under `~/WebApps` (including `~/WebApps/html`) and `~/jobrunner`, capturing repository path, primary remote URL, all remote mappings, current branch, uncommitted-change flag, modified/untracked file counts, latest commit (`hash`, `short_hash`, `date`, `author`, `subject`), and worktree/backup flags.
- `secret_paths`: Categorised file and directory paths for SSH keys, GPG keyring, `pass` password store (`~/.password-store`), nginx `.htpasswd` files, Let's Encrypt TLS certificates, CLI/agent credentials, and project `.env` / `.env.local` files.
- `dotfiles`: Summary and file manifest of non-secret dotfiles copied when `--dotfiles` is enabled.
- `restore-notes`: Structured step-by-step restoration guide embedded directly in the JSON manifest.

## Secret and Credential Policy

- Secret, token, key, certificate, and password contents are never included in `pi-YYYYMMDD.json` or copied into `./output/dotfiles/`.
- Only file paths and existence flags (`true`, `false`, or `"permission_restricted"`) are recorded under `secret_paths`.
- Plain-text `Access Password` lines present in `~/WebApps/services.md` are omitted during parsing; their line numbers and section headings are logged under `secret_paths.redacted_documentation_secrets`.
- In `--dotfiles` mode, every candidate file is checked against both filename exclusions (`.env*`, `id_*`, `authorized_keys`, `*.pem`, `*.key`, `.htpasswd*`, `credentials*`, `hosts.yml`, `access-token`, `.cli-m365*`) and content patterns (private key headers, API tokens, inline secret assignments) before copying.

## Cross-Reference Findings (`~/WebApps/services.md`)

Cross-referencing `~/WebApps/services.md` against `/etc/systemd/system/` and `~/.config/systemd/user/` identified the following discrepancies (also recorded in `services_md_cross_reference.discrepancies`):

- Nine custom systemd units are active or enabled on the Raspberry Pi without a corresponding `##` section in `~/WebApps/services.md`:
  - `christmas-card-crm.service` (`/home/pi/WebApps/christmas-card-crm`).
  - `exceltool.service` (`/home/pi/WebApps/exceltool`).
  - `ifc2cobie.service` (`/home/pi/WebApps/ifc2Cobie`).
  - `mgkform.service`, `mgkform-updater.service`, and `mgkform-updater.timer` (`/home/pi/WebApps/mgkform`).
  - `pricetracker.service` (`/home/pi/WebApps/pricetracker`).
  - `uww-generator.service` (`/var/www/html/UWW/UWW-Generator`).
  - `webpodcasts.service` (`/home/pi/WebApps/WebPagePodcasts`).
- Line 48 of `~/WebApps/services.md` contains an unheaded Markdown table row for `mgkform` rather than a standard service section.
- The `pdf2markdown` section in `~/WebApps/services.md` lists `/home/pi/WebApps/Pdf2Markdown/webapp/` as its location, whereas the actual `WorkingDirectory` in `/etc/systemd/system/pdf2markdown.service` is `/home/pi/WebApps/Tools/Pdf2Markdown/webapp`.

## Restore Notes

Follow the steps below to restore this Raspberry Pi from `pi-YYYYMMDD.json` (`pi-date.json`) and `./output/dotfiles/`.

### 1. Base Operating System and Core Packages

1. Update Raspberry Pi OS (Debian 13 Trixie, 64-bit `aarch64`) and install system packages:
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   sudo apt-get install -y git nginx certbot python3-certbot-nginx fish tmux vim pass gnupg sqlite3 imagemagick build-essential curl
   ```
2. Install `uv` for Python environment management and `bun` for JavaScript/TypeScript projects:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   curl -fsSL https://bun.sh/install | bash
   ```
3. Install OpenJDK 21 (`sudo apt-get install -y openjdk-21-jre-headless`) if restoring the standalone `xwiki.service` test instance.

### 2. Restore Secrets, Keys, and Credentials Out-of-Band

Restore all paths listed under `secret_paths` in `pi-date.json` from secure offline storage:

1. **SSH Keys and Multi-Account Host Config**:
   - Restore `/home/pi/.ssh/id_ed25519_personal`, `/home/pi/.ssh/id_ed25519_wta`, and `/home/pi/.ssh/authorized_keys`.
   - Set strict permissions:
     ```bash
     chmod 700 ~/.ssh
     chmod 600 ~/.ssh/id_ed25519_personal ~/.ssh/id_ed25519_wta ~/.ssh/authorized_keys
     ```
2. **GPG and Password Store (`pass`)**:
   - Restore `/home/pi/.gnupg` and `/home/pi/.password-store` (including `gmail-cleaner` and `secret_service`), ensuring key `5FAC63C894A51AA4` is imported and trusted.
3. **Nginx HTTP Basic Auth Files**:
   - Restore or recreate `/etc/nginx/.htpasswd-biogenic-notes`, `/etc/nginx/.htpasswd-insights`, and `/etc/nginx/.htpasswd-uwwtools`.
4. **CLI and Agent Credentials**:
   - Re-authenticate GitHub CLI (`gh auth login`), Claude Code (`claude auth`), and restore `/home/pi/.supabase/access-token`, `/home/pi/.cli-m365-*.json`, and `/home/pi/duckdns/duck.sh`.

### 3. Restore Non-Secret Dotfiles

Copy the archived dotfiles back into `/home/pi`:

```bash
cp -a ./output/dotfiles/. ~/
```

This restores `.bashrc`, `.profile`, `.zshrc`, `.gitconfig`, `.gitconfig-personal`, `.gitconfig-wta`, `.tmux.conf`, `.vimrc`, `.vim_runtime/my_configs.vim`, `.ssh/config`, `.config/fish/`, `.config/git/ignore`, `.config/nvim/`, and `.config/systemd/user/pass-secret-service.service`.

### 4. Recreate Directory Layout and Web Root Symlink

Ensure `/var/www/html` and `/home/pi/WebApps/html` are linked so static deployments are served automatically:

```bash
sudo mkdir -p /var/www/html
sudo chown -R pi:pi /var/www/html
mkdir -p ~/WebApps ~/WebApps/Tools ~/jobrunner
ln -sfn /var/www/html ~/WebApps/html
```

### 5. Clone Git Repositories and Rebuild Environments

1. Iterate through `git_projects.projects` in `pi-date.json`. Because `~/.ssh/config` and `~/.gitconfig` define the `github.com-wta` and `github.com-personal` host aliases, cloning each repository with its recorded `remote_url` automatically selects the matching SSH key and Git identity:
   ```bash
   git clone <remote_url> <path>
   git -C <path> checkout <branch>
   ```
2. For repositories marked with `"remote_url": null` (local-only repositories), restore from filesystem backups.
3. Restore all project `.env` and `.env.local` files listed under `secret_paths.project_env_files`.
4. Rebuild runtime dependencies:
   - Python projects (`pyproject.toml`): `uv sync` (or `uv venv && uv pip install -r requirements.txt`).
   - JavaScript/TypeScript projects (`package.json`): `bun install` and `bun run build` where nginx serves a `dist/` directory.

### 6. Restore Systemd Services and Timers

1. Copy or recreate the unit files listed in `systemd_services.custom_services_and_timers` under `/etc/systemd/system/` (for `"scope": "system"`) and `~/.config/systemd/user/` (for `"scope": "user"`).
2. Reload systemd and enable active units:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now aowiki.service biogenic-keepalive.timer biogenic-notes.service \
     carbonbench.service christmas-card-crm.service drawio2pptx.service \
     elevation-planner-dxf.service exceltool.service gmail-cleaner.service \
     ifc2cobie.service insights.service materialcatalogue-api.service \
     mgkform.service mgkform-updater.timer ninsteam.service pdf2markdown.service \
     playbook.service playbook-dev.service pricetracker.service simplecarbon.service \
     uww-generator.service uww-l3-convertor.service webpodcasts.service \
     wta-node-studio.service xwiki.service

   systemctl --user daemon-reload
   systemctl --user enable --now pass-secret-service.service
   ```

### 7. Restore Nginx Configuration and TLS Certificates

1. Restore `/etc/nginx/sites-available/architools.conf`, `/etc/nginx/snippets/biogenic-gate.conf`, and symlink `/etc/nginx/sites-enabled/architools.conf`.
2. Restore `/etc/letsencrypt` or obtain fresh certificates via Certbot:
   ```bash
   sudo certbot --nginx -d architools.duckdns.org -d architools.mooo.com -d architools.drawingtable.net
   ```
3. Verify and reload nginx:
   ```bash
   sudo nginx -t && sudo nginx -s reload
   ```

### 8. Restore User Crontab

Install the user cron jobs recorded in `cron.user_crontab.entries`:

```cron
0 2 * * * /home/pi/WebApps/Wiki/Playbook/scripts/backup_db.sh
*/15 * * * * cd /home/pi/jobrunner && /home/pi/.local/bin/uv run python -m src.main >> data/cron.log 2>&1
# AoWiki Automation
# Ingest all new raw sources daily at 3 AM
0 3 * * * cd /home/pi/WebApps/AOwiki && /home/pi/.bun/bin/bun run ingest >> /home/pi/WebApps/AOwiki/logs/ingest.log 2>&1
# Run wiki health check daily at 4 AM
0 4 * * * cd /home/pi/WebApps/AOwiki && /home/pi/.bun/bin/bun run lint >> /home/pi/WebApps/AOwiki/logs/lint.log 2>&1
```
