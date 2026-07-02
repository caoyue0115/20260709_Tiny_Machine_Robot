# Guangzhou Validation

Validated:
- `tiny.praystack.top` healthz returned JSON.
- Docker Compose stack started under `/app/20260701_Tiny_Machine_Robot/current`.
- API is running behind the existing Guangzhou Nginx proxy on `127.0.0.1:8010`.
- Coffee index was built on the server with domain `coffee` and 4 documents.
- Public WebSocket upgrade works for `GET /api/v5/realtime/opus-stream`.
- Public realtime audio downlink works for `GET /api/v3/realtime/sessions/{session_id}/audio`.
- Full-chain Opus smoke passed through Volcengine ASR, coffee RAG, Qwen 3.5 Flash, and Qwen realtime TTS.

Current provider health:
- `api=ok`
- `redis=ok`
- `sqlite=ok`
- `asr=ok`
- `llm=ok`
- `tts=ok`

Runtime notes:
- `PUBLIC_BASE_URL=http://tiny.praystack.top` is used so ESP32 can fetch the realtime audio stream over HTTP.
- `REALTIME_TTS_MODEL=qwen3-tts-flash-realtime-2025-11-27` is used with the configured realtime voice.
- The active fallback Docker images include `libopus0`; the source Dockerfile already declares this dependency for clean rebuilds.
- Guangzhou Nginx keeps most HTTP traffic redirected to HTTPS, but allows the ESP32 realtime WebSocket and audio downlink paths on port 80.

Latest cloud smoke:
- Question: `手冲咖啡为什么会偏酸？`
- ASR provider: `volcengine`
- Answer: `手冲偏酸常因研磨太粗、水温偏低或萃取时间不足。试试调细研磨度、提高水温或延长冲煮时间来平衡风味。`
- Public audio stream returned `200 OK`, `x-audio-format: opus`, `x-audio-packetization: framed-v1`.

Open before firmware acceptance:
- Complete a physical COM6 GPIO7 or wake-word run and confirm the board plays the cloud answer.

Secrets:
- Runtime credentials stayed on the server.
- No secret values were printed or committed.
