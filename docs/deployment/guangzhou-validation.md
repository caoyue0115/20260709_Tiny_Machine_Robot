# Guangzhou Validation

Validated:
- `tiny.praystack.top` healthz returned JSON.
- Docker Compose stack started under `/app/20260701_Tiny_Machine_Robot/current`.
- API is running behind the existing Guangzhou Nginx proxy on `127.0.0.1:8010`.
- Coffee index was built on the server with domain `coffee` and 4 documents.

Current provider health:
- `api=ok`
- `redis=ok`
- `sqlite=ok`
- `asr=ok`
- `llm=down`
- `tts=down`

Open before firmware acceptance:
- Add Qwen/DashScope runtime credentials on the server so LLM and realtime TTS can pass health and device Q&A playback.
- Remote Docker build with `apt-get update` hung on this host; current stack used a fallback runtime image copied from the existing server image.

Secrets:
- Runtime credentials stayed on the server.
- No secret values were printed or committed.
