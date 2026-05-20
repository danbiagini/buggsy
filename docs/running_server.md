# Running the Buggsy server

The server side is four pieces:

- **Mosquitto** — MQTT broker, containerized.
- **TTS** — Piper-based HTTP service, containerized. Exposes `POST /synthesize`.
- **STT** — faster-whisper HTTP service, containerized. Exposes `POST /transcribe`. (Wired into the orchestrator once #24/#25 land — bring it up now to validate the path.)
- **Orchestrator** — Python service. On wake event: asks the planner for tool calls, dispatches them through the skill framework (`say`, `play_move`).

## Bring up the broker + TTS + STT

```bash
cd server/compose
docker compose up -d --build       # --build first time, or after editing tts/ or stt/
docker logs -f buggsy-mosquitto
docker logs -f buggsy-tts
docker logs -f buggsy-stt
```

- **Mosquitto**: `eclipse-mosquitto:2` on `0.0.0.0:1883`. Anonymous v1 (LAN-only assumption — add `password_file` + TLS before exposing). Persistence and logs bind-mounted under `mosquitto/{data,log}/`.
- **TTS**: Piper FastAPI on `0.0.0.0:8001`. Voice (`en_US-amy-medium`, ~63MB) baked into the image at build time. Health check: `curl http://localhost:8001/health`.
- **STT**: faster-whisper FastAPI on `0.0.0.0:8002`. Model downloaded on first run into the `stt-cache` named volume (~500MB for `small.en`, ~3GB for `large-v3` — persists across container restarts). Health check: `curl http://localhost:8002/health`.

### STT model selection

Default is `small.en` — fast load, fine for short office commands. Override per-deployment via env:

```yaml
# in server/compose/docker-compose.yml under the stt service:
environment:
  BUGGSY_STT_MODEL: large-v3        # ~3GB, best accuracy in noisy rooms
  BUGGSY_STT_DEVICE: cuda           # cuda | cpu | auto
  BUGGSY_STT_COMPUTE_TYPE: float16  # default | float16 | int8
```

VRAM budget on the 16GB 4060 Ti:

| Model     | Approx VRAM | Notes                                    |
| --------- | ----------- | ---------------------------------------- |
| `tiny.en` | <1 GB       | Distilled English-only                   |
| `base.en` | ~1 GB       |                                          |
| `small.en`| ~1.5 GB     | **Default**, balanced                    |
| `medium.en`| ~3 GB      |                                          |
| `large-v3`| ~3 GB       | Multilingual, design-doc production target |

Coresident with `qwen2.5:14b-instruct` (~9 GB), large-v3 + the LLM still leaves ~4 GB headroom.

### Quick STT hand test

```bash
# Record or grab a short WAV clip, then:
python -c "import base64,sys; sys.stdout.write(base64.b64encode(open('clip.wav','rb').read()).decode())" \
  | jq -Rsn '{audio_b64: input, language: "en"}' \
  | curl -sX POST http://localhost:8002/transcribe \
         -H 'content-type: application/json' -d @-
```

### GPU passthrough

The `stt` service in compose reserves an NVIDIA GPU via the `deploy.resources.reservations.devices` block. Requires [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) on the host. To run CPU-only (slow, but works on dev boxes without a GPU), comment out the `deploy:` block — faster-whisper auto-falls-back when `BUGGSY_STT_DEVICE=auto`.

#### Wiring nvidia-container-toolkit into Docker

Installing the toolkit isn't enough — Docker needs to be told to register the `nvidia` runtime. If `docker compose up stt` fails with `could not select device driver "nvidia" with capabilities: [[gpu]]`, run:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify:

```bash
docker info | grep -i runtime
# expect: Runtimes: io.containerd.runc.v2 nvidia runc

docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
# expect: a table listing your GPU
```

If the host `nvidia-smi` works but the container one doesn't, you likely have the deprecated `nvidia-docker2` package installed instead of `nvidia-container-toolkit` — uninstall the former, install the latter, repeat the `nvidia-ctk` step.

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
| `BUGGSY_VOICE_ID` | from config | Voice to request from TTS (overrides `tts.voice_id` in config) |
| `BUGGSY_CONFIG` | `config/buggsy.yaml` | Path to the YAML config file |

STT-side env vars (set on the **`stt` container**, not the orchestrator):

| Var | Default | Notes |
| --- | --- | --- |
| `BUGGSY_STT_MODEL` | `small.en` | Any faster-whisper model id (see table above) |
| `BUGGSY_STT_DEVICE` | `auto` | `auto` \| `cuda` \| `cpu` |
| `BUGGSY_STT_COMPUTE_TYPE` | `default` | `default` \| `float16` \| `int8` |

The orchestrator will auto-reconnect on broker disconnect.

## Config file

Both orchestrator and robot agent read `config/buggsy.yaml` (override with `BUGGSY_CONFIG`). Env vars override individual fields. See the [example file](../config/buggsy.yaml) for the schema; key orchestrator fields:

- `greeting.static_phrase` — what Buggsy says on wake (until #-future LLM source lands).
- `tts.voice_id` — default Piper voice (override per request later).

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
