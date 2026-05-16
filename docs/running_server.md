# Running the Buggsy server

The server side is two pieces (for now):

- **Mosquitto** — MQTT broker, containerized.
- **Orchestrator** — Python service that wires events between robot and (eventually) TTS/LLM.

In v1 the orchestrator is a dummy that just replies to wake events with a placeholder speak command. #6 adds real TTS.

## Bring up the broker

```bash
cd server/compose
docker compose up -d
docker logs -f buggsy-mosquitto    # tail to verify
```

This runs `eclipse-mosquitto:2` on `0.0.0.0:1883` with anonymous auth (LAN-only assumption for v1 — add `password_file` + TLS before exposing externally).

Persistence and logs are bind-mounted under `server/compose/mosquitto/{data,log}/` so retained messages survive container restarts.

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

The orchestrator will auto-reconnect on broker disconnect.

## End-to-end smoke (broker + orchestrator + robot)

1. **Server box:** `docker compose up -d` (broker), then `python -m server.orchestrator` in another shell.
2. **Robot:** `BUGGSY_MQTT_HOST=<server_ip> /venvs/apps_venv/bin/python -m robot.agent.agent`
3. Say "hey jarvis" (or `kill -USR1 $(pgrep -f robot.agent.agent)` for a fake wake).

Expected:
- Robot logs `WAKE confidence=...`
- Orchestrator logs `wake received: confidence=...` then `published placeholder speak command`
- Robot logs `SPEAK received: text='(placeholder greeting — TTS arrives in #6)'`
- Orchestrator logs robot state every 10s (retained heartbeat)

## Inspecting topics

Quick way to eavesdrop on the bus:

```bash
docker exec -it buggsy-mosquitto mosquitto_sub -t 'buggsy/#' -v
```
