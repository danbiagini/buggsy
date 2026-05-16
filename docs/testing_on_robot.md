# Testing the wake detector on the Reachy Mini

The Pollen image ships Python 3.12 in a venv at `/venvs/apps_venv/` — use
that interpreter for everything below.

## 1. Get network access

Use the **Reachy Mini Control** app (https://hf.co/reachy-mini/#/download)
to configure Wi-Fi the first time. After that the robot is reachable at
`reachy-mini.local`.

SSH credentials:

```
ssh pollen@reachy-mini.local   # password: root
```

Sanity check that the robot OS is healthy:

```bash
reachyminios_check
```

## 2. Clone and install on the robot

```bash
ssh pollen@reachy-mini.local
cd /home/pollen
git clone https://github.com/danbiagini/buggsy.git
cd buggsy
git checkout issue-3/wake-detection   # or main once merged

# Use the Pollen-provided Python 3.12 venv
/venvs/apps_venv/bin/pip install -e shared/ -e robot/

# PortAudio (only if not already on the image)
sudo apt install -y libportaudio2
```

## 3. Preflight

```bash
/venvs/apps_venv/bin/python -m robot.scripts.preflight
```

Should report OK on Python version, audio inputs, and openwakeword imports.
Note the default input device the robot reports — if it isn't the built-in
USB mic you'll need `BUGGSY_AUDIO_DEVICE=<index_or_name>` later.

## 4. Fetch a wake model

```bash
/venvs/apps_venv/bin/python -m robot.scripts.fetch_wake_model
```

Copies `hey_jarvis_v0.1.onnx` into `robot/wake_models/`.

## 5. Run dev_smoke

```bash
/venvs/apps_venv/bin/python -m robot.agent.dev_smoke
```

Then say **"hey jarvis"** — you should see `WAKE! confidence=...` logged.

In a second SSH session, measure CPU usage:

```bash
top -p $(pgrep -f dev_smoke)
```

### Tunables (env vars)

| Var | Default | Notes |
| --- | --- | --- |
| `BUGGSY_WAKE_THRESHOLD` | 0.5 | Wake confidence cutoff. |
| `BUGGSY_VAD_THRESHOLD` | 0 (off) | Silero VAD; filters false-positive wakes but is *not* a CPU gate (openWakeWord runs the model regardless). Turn on if FPs become a problem. |
| `BUGGSY_SPEEX_NS` | 0 | Set to `1` to enable Speex noise suppression (needs `pip install speexdsp-ns` or `pip install -e robot/[speex]`). |
| `BUGGSY_AUDIO_DEVICE` | (default) | sounddevice device index or name. |

### Measured CPU on Reachy Mini Wireless (CM4 4GB), 2026-05-16

`dev_smoke` steady-state: **~33% of one core** (out of 4 cores = ~8% total capacity).
Per-component breakdown via `python -m robot.scripts.timing_probe`:

| component | cpu_share (of one core) |
| --- | --- |
| openWakeWord preprocessor (melspec + embedding) | ~30% |
| wake-model inference (`hey_jarvis_v0.1`) | ~1% |

Judged acceptable — full CPU-budget analysis lives in the discussion on #10.
A real CPU gate (e.g. webrtcvad before `model.predict()`) would skip the
preprocessor on silence and cut idle CPU substantially. Revisit if camera
streaming or battery life applies pressure.

## 6. Run the agent (wake → antennae up → cooldown → antennae down)

```bash
/venvs/apps_venv/bin/python -m robot.agent.agent
```

Then say "hey jarvis". You should see antennae raise within ~100ms; after
5s of silence they lower again.

### Trigger a fake wake (no need to speak)

In a second SSH session:

```bash
kill -USR1 $(pgrep -f robot.agent.agent)
```

Same flow, on demand — useful when iterating on motion without yelling at
the robot.

### Agent env vars

| Var | Default | Notes |
| --- | --- | --- |
| `BUGGSY_COOLDOWN_S` | 5.0 | Seconds attentive after last wake before returning to resting. |
| `BUGGSY_MOCK_MOTION` | unset | Set to `1` to skip the Reachy SDK (run on a dev mac without a robot). |
| `BUGGSY_DAEMON_URL` | http://localhost:8000 | Reachy daemon base URL. |
| `BUGGSY_SKIP_DAEMON_WAKE` | unset | Set to `1` to skip the daemon wake/sleep calls (e.g. if Reachy Mini Control has already woken the robot). |

Plus everything from `dev_smoke` (`BUGGSY_WAKE_MODEL`, `BUGGSY_WAKE_THRESHOLD`, etc.).

### Daemon wake/sleep

The Reachy daemon starts in a sleeping state (`--no-wake-up-on-start`). The
SDK can't establish its WebSocket telemetry until motors are powered. The
agent handles this by POSTing to the daemon's HTTP API on startup and
shutdown:

```
POST /api/move/play/wake_up      # on startup
POST /api/move/play/goto_sleep   # on clean shutdown
```

If you've already woken the robot via Reachy Mini Control, set
`BUGGSY_SKIP_DAEMON_WAKE=1` to avoid the redundant wake animation.

## Editing from your mac (optional)

The Pollen-recommended workflow is sshfs-mount the robot's clone:

```bash
# on the mac
mkdir -p ~/reachy_dev
sshfs pollen@reachy-mini.local:/home/pollen/buggsy ~/reachy_dev \
    -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3
```

Or use VS Code's Remote-SSH extension and connect to `pollen@reachy-mini.local`.
