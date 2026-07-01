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

Health check:

```bash
curl -fsS http://127.0.0.1/healthz
curl -fsS http://tiny.praystack.top/healthz
```
