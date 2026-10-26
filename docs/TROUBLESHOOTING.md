# Local development troubleshooting

Start with `dev.ps1 doctor`, `dev.ps1 status`, then `dev.ps1 logs --service api --tail 80`. Substitute `bash dev.sh` on Unix. Never paste config files, tokens, passwords or complete environment dumps into an issue.

| Symptom | Diagnosis and safe recovery |
|---|---|
| Docker unavailable / pipe denied | Start Docker Desktop in Linux-container mode. Confirm your user can run `docker info`. A sandbox may need an approved host execution context; do not bypass restrictions. No DB changes occur before the check. |
| Python not found / wrong version | Install 64-bit CPython 3.11/3.12 and reopen the terminal. Windows' Store alias is not a Python installation. Use an explicit compatible Python to invoke `tools/dev/dev.py setup` if needed. |
| Node rejected / Vite engine error | Use Node 24 LTS or 22.12+. Old instructions mentioning Node 20 predate Vite 8. Reopen the terminal and rerun setup. |
| Dependency installation fails | Inspect the installer output, disk space, configured package index and organization proxy. Resolve approved network access; do not copy a personal venv as a fresh-clone fix. Rerun setup. No production credentials are needed. |
| Port occupied | The launcher refuses unowned listeners. Stop only your positively identified process, or choose a free port in `.dev/config.json` while down. URLs/CORS/proxy are derived together. Never kill by port alone. |
| PostgreSQL not ready | Inspect the checkout's Compose status/logs. Do not substitute another database URL. Verify Docker resources/disk. No schema reset is a recovery step. |
| Missing vector/migration | Run `db-status`, then `migrate`. Use the pgvector image, not plain postgres. A migration error must be fixed/understood; do not mark history applied manually. |
| Restricted-role permission failure | Run `db-check`; check that all migrations applied and the persisted app password matches. Do not grant superuser or disable RLS. |
| Redis unavailable | Check the project Redis container and selected loopback port. Do not flush a shared Redis or reuse another runtime's namespace. |
| API returns 200 on /health but app fails | Use `/health/ready`, check frontend `/api/health/ready`, DB/migration checks and service logs. Liveness alone is insufficient. |
| CORS / old Checkout return URL | Use the exact printed frontend origin. Restart after changing ports. Launcher derives CORS, frontend base URL and Vite target from one config. Use fresh test Checkout sessions only in separately authorized payment testing. |
| Worker failed | Inspect its named log and `status`. Startup checks registration/heartbeat/initialization; it never treats an exited process as ready. Fix the actual dependency or SQL error. |
| AI unavailable / COST_NOT_CONFIGURED | Missing model libraries/weights, provider credentials or verified rate schedules are distinct. Use `setup --models` for model libraries; configure approved test providers/cost evidence separately. No fake rates are seeded. |
| OTP email absent | Open printed Mailpit inbox; inspect API SMTP errors and mail container health. Local mail is captured, not sent to the internet. |
| Stale command lock | Read `.dev/command.lock`, inspect that PID and its command/creation time. Remove only a proven abandoned lock. Never remove an active lock to launch competing commands. |
| PID identity mismatch | A process may have exited and its PID been reused. Inspect before editing ownership metadata. The launcher refuses to stop an unidentified process. |
| Setup config copied from another path | Do not reuse another checkout's `.dev`. It belongs to that checkout and may own live resources. Preserve it; run setup in a genuinely fresh checkout. |
| Unsupported OS/model wheel | Windows is the primary verified workflow. Linux/macOS use the shared entry point but availability of Python ML wheels/OS binaries varies; consult the recorded verification status. |

## Reset policy

There is no automatic destructive reset command. `down` retains PostgreSQL, Redis and storage volumes. Manual removal requires verifying the exact checkout/project labels and backing up local data first. Never use an unqualified `docker system prune` or a broad recursive deletion as startup recovery.

## Reporting a defect

Include source commit, OS/runtime versions, failing command, service name, redacted error and whether it occurs in a fresh checkout. Report actual readiness and expected behavior. Keep private config, account identifiers, provider resources and sensitive payloads out of committed evidence.
