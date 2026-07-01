# Guangzhou Deployment Runbook

Target service: `Tiny Coffee Machine`

Public entry:
- Domain: `tiny.praystack.top`
- SSH alias: `gz-admin`
- Host: `8.163.37.82`
- User: `hanxiao_zhu_gz`
- Port: `22`

Runtime layout:

```text
/app/20260701_Tiny_Machine_Robot
/app/20260701_Tiny_Machine_Robot/data
/app/20260701_Tiny_Machine_Robot/indices
/app/20260701_Tiny_Machine_Robot/logs
```

Takeover rule:
- Back up the currently running service before stopping it.
- Do not print `.env` contents.
- Reuse runtime credentials by copying the old `.env` file only on the server.
- Run health checks before device flashing.
- Roll back by restoring the previous compose directory and starting its compose stack.

Package from the local bring-up tree:

```bash
git archive --format=tar.gz -o tiny-machine-robot.tar.gz HEAD
scp tiny-machine-robot.tar.gz gz-admin:/tmp/tiny-machine-robot.tar.gz
```

Back up, copy credentials without printing them, and start:

```bash
ssh gz-admin
set -euo pipefail

APP_DIR=/app/20260701_Tiny_Machine_Robot
RELEASE_TGZ=/tmp/tiny-machine-robot.tar.gz
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/app/20260701_Tiny_Machine_Robot.backup.$TS

sudo mkdir -p /app
if [ -d "$APP_DIR" ]; then
  sudo cp -a "$APP_DIR" "$BACKUP_DIR"
fi

if [ -f "$APP_DIR/docker-compose.guangzhou.yml" ]; then
  (cd "$APP_DIR" && sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml down)
elif [ -f "$APP_DIR/docker-compose.yml" ]; then
  (cd "$APP_DIR" && sudo docker compose -p tiny_coffee_machine -f docker-compose.yml down)
fi

sudo mkdir -p "$APP_DIR"
sudo tar -xzf "$RELEASE_TGZ" -C "$APP_DIR"
sudo mkdir -p "$APP_DIR/data" "$APP_DIR/indices" "$APP_DIR/logs"

if [ -f "$BACKUP_DIR/.env" ]; then
  sudo cp -p "$BACKUP_DIR/.env" "$APP_DIR/.env"
fi
sudo test -s "$APP_DIR/.env"

cd "$APP_DIR"
sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml config --quiet
sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml up -d --build
sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml ps
```

Health checks:

```bash
curl -fsS http://127.0.0.1/healthz
curl -fsS http://tiny.praystack.top/healthz
```

Rollback:

```bash
ssh gz-admin
set -euo pipefail

APP_DIR=/app/20260701_Tiny_Machine_Robot
ROLLBACK_DIR=/app/20260701_Tiny_Machine_Robot.backup.YYYYMMDD_HHMMSS
FAILED_DIR=/app/20260701_Tiny_Machine_Robot.failed.$(date +%Y%m%d_%H%M%S)

cd "$APP_DIR"
sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml down
cd /app
sudo mv "$APP_DIR" "$FAILED_DIR"
sudo cp -a "$ROLLBACK_DIR" "$APP_DIR"

cd "$APP_DIR"
if [ -f docker-compose.guangzhou.yml ]; then
  sudo docker compose -p tiny_coffee_machine -f docker-compose.guangzhou.yml up -d --build
else
  sudo docker compose -p tiny_coffee_machine -f docker-compose.yml up -d --build
fi
curl -fsS http://127.0.0.1/healthz
```
