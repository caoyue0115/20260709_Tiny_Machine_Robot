# Tiny Coffee Machine / 小机仔

Tiny Coffee Machine / 小机仔 is the current bring-up repo for the ESP voice coffee assistant. The active bring-up target is the Guangzhou entry:

```text
https://tiny.praystack.top
```

This README is intentionally short. Detailed firmware, deployment, and handoff docs will be filled in by later tasks.

## Bring-Up Chain

- Device audio path: realtime Opus uplink from the board to the backend session.
- ASR target: Volcengine ASR for streaming recognition.
- Reasoning path: coffee RAG snippets from `data/coffee`, then Qwen 3.5 Flash.
- Voice output: Qwen realtime TTS, streamed back for low-latency playback.
- OTA code and configuration hooks are retained in the repo, but OTA is inactive for the current bring-up.

## Coffee RAG

Coffee knowledge lives under:

```text
data/coffee
```

Keep this directory focused on coffee-machine, brewing, bean, and drink-domain material used by the active RAG retriever.

## ASR Hotwords

The ASR vocabulary helper defaults to the coffee hotword list:

```bash
python scripts/create_asr_vocabulary.py
```

Default inputs:

```text
config/asr_hotwords.coffee.json
prefix: coffeeasr
```

To update an existing vocabulary table:

```bash
python scripts/create_asr_vocabulary.py --vocabulary-id vocab-xxxx
```

The helper prints a JSON summary and an `ASR_VOCABULARY_ID=...` line suitable for local environment configuration.

## Configuration And Secrets

- Use environment variables or local `.env` files for service credentials.
- Do not commit real API keys, access tokens, SSH keys, Wi-Fi credentials, or production secrets.
- Example values in tracked files must stay fake or placeholder-only.

## Useful Checks

```bash
$env:PYTHONPATH='.'; python -m pytest tests/test_asr_provider.py tests/test_smoke_scripts.py -q
$env:PYTHONPATH='.'; python -m pytest tests/test_tiny_coffee_rag.py tests/test_opus_uplink.py -q
```
