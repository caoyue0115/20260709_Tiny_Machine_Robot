# Tiny Coffee Machine

`Tiny Coffee Machine` / `小机仔` is an ESP32-S3 voice Q&A coffee companion.

Phase 1 runs the realtime Opus voice chain:

```text
小明同学 wake word -> Opus uplink -> Volcengine ASR -> coffee RAG -> Qwen 3.5 Flash -> Qwen realtime TTS -> device playback
```

## Phase 1 Scope

- ESP32-S3 16MB Flash + 8MB PSRAM voice board.
- Guangzhou cloud entry: `tiny.praystack.top`.
- Realtime Opus endpoint: `/api/v5/realtime/opus-stream`.
- General coffee knowledge base.
- OTA code retained but inactive.

## Local Cloud

```powershell
copy .env.example .env
docker compose up --build
```

## Coffee Index

```powershell
$env:PYTHONPATH='.'
python scripts/ingest_coffee.py
```

## Firmware

See `docs/firmware/windows-com6.md`.
