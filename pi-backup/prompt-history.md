# pi-backup - Prompt History

## 2026-10-30

### Prompt 1
> Build a small uv-managed Python tool that writes pi-YYYYMMDD.json (named pi-date.json in the notes) capturing what is needed to quickly restore this Raspberry Pi: running and enabled systemd services (name, unit file path, state), cron entries, nginx sites-enabled, and every git project under ~/WebApps and ~/jobrunner (path, remote URL, branch, uncommitted-change flag, latest commit). Cross-reference ~/WebApps/services.md. Do not include secrets, tokens or password files; list their paths only. Add a restore-notes section and a README. Output the JSON to ./output/ and also offer a --dotfiles mode that copies key dotfiles (non-secret) into the output folder. Do not install or change any services. Use UK English.
