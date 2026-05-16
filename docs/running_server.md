# Running the Buggsy server

The server side is three pieces:

- **Mosquitto** — MQTT broker, containerized.
- **TTS** — Piper-based HTTP service, containerized. Exposes `POST /synthesize`.
- **Orchestrator** — Python service. On wake event: synthesizes greeting text via TTS, publishes inline base64 audio in a `SpeakCommand`.

## Bring up the broker + TTS

```bash
cd server/compose
docker compose up -d --build       # --build first time, or after editing tts/
docker logs -f buggsy-mosquitto
docker logs -f buggsy-tts
```

- Mosquitto: `eclipse-mosquitto:2` on `0.0.0.0:1883`. Anonymous v1 (LAN-only assumption — add `password_file` + TLS before exposing). Persistence and logs bind-mounted under `mosquitto/{data,log}/`.
- TTS: Piper FastAPI on `0.0.0.0:8001`. Voice (`en_US-amy-medium`, ~63MB) baked into the image at build time. Health check: `curl http://localhost:8001/health`.

## Run the orchestrator

From the repo root:

```bash
pip install -e shared/ -e server/
python -m server.orchestrator
```

Env vars:

| Var | Default | Notes |
| --- | --- | --- |
| `BUGGSY_MQTT_HOST` | localhost | Broker host |
| `BUGGSY_MQTT_PORT` | 1883 | Broker port |
| `BUGGSY_TTS_URL` | http://localhost:8001 | TTS service base URL |
| `BUGGSY_VOICE_ID` | (server default) | Voice to request from TTS |

The orchestrator will auto-reconnect on broker disconnect.

## End-to-end smoke (broker + orchestrator + robot)

1. **Server box:** `docker compose up -d` (broker), then `python -m server.orchestrator` in another shell.
2. **Robot:** `BUGGSY_MQTT_HOST=<server_ip> /venvs/apps_venv/bin/python -m robot.agent.agent`
3. Say "hey jarvis" (or `kill -USR1 $(pgrep -f robot.agent.agent)` for a fake wake).

Expected:
- Robot logs `WAKE confidence=...`
- Orchestrator logs `wake received: ...` then `published speak: NNN bytes audio`
- Robot logs `SPEAK received: text='Hi Dan, ...' audio=inline` and `audio_out: playing ... frames`
- You **hear the greeting** from the Reachy speaker
- Orchestrator logs `robot finished speaking ...` (spoke_done)
- Orchestrator logs robot state every 10s (retained heartbeat)

## Inspecting topics

Quick way to eavesdrop on the bus:

```bash
docker exec -it buggsy-mosquitto mosquitto_sub -t 'buggsy/#' -v
```
