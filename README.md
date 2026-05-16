# Buggsy

Buggsy is an office assistant robot built on the [Reachy Mini Wireless](https://github.com/pollen-robotics/reachy_mini). It's the persona for a team of AI agents.

The v1 feature is wake-word detection plus a spoken greeting — see [issue #1](https://github.com/danbiagini/buggsy/issues/1) for the full design and child issues.

## Layout

```
robot/    # runs on the Reachy Mini (Pi CM4)
server/   # orchestrator, TTS, and config services (Ubuntu + GPU)
shared/   # protocol interfaces and MQTT message schemas (used by both)
config/   # buggsy.yaml — shared config for robot and server
docs/
```

## Installing

### Robot (Reachy Mini)

Use the wrapper script — it handles the `openwakeword` / `tflite-runtime` install workaround (see below):

```bash
sudo apt install -y libportaudio2
PIP=/venvs/apps_venv/bin/pip ./robot/scripts/install.sh
```

Full walkthrough: [docs/testing_on_robot.md](docs/testing_on_robot.md).

### Server

Plain pip works — no special steps:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e shared/ -e server/
```

Full walkthrough: [docs/running_server.md](docs/running_server.md).

### Dev mac

If you want to run the robot agent in mock-motion mode on your laptop, use the same wrapper script as the robot:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
./robot/scripts/install.sh        # uses the .venv's pip
```

## Adding a dep to the robot package

Because of the openwakeword/tflite workaround, robot runtime deps are listed in **two** places and must stay in sync:

1. `robot/pyproject.toml` — the canonical declaration (for IDEs, CI, future packaging).
2. `robot/scripts/install.sh` — the explicit list installed by the bootstrap script (since the editable install uses `--no-deps` to avoid pip re-resolving openwakeword's transitive deps).

If you add or change a robot dep, update both. Sorry — not great. Tracked: filing a follow-up to either parse the pyproject in shell or make the script generate from it.

## Why the install workaround?

`openwakeword>=0.6` hard-depends on `tflite-runtime`, which has no wheels for Python 3.12 / aarch64 (the Reachy Mini's runtime). We use the ONNX backend exclusively, so `tflite-runtime` is dead weight. The script installs `openwakeword` with `--no-deps`, supplies the deps we actually need (`onnxruntime`, `scipy`, etc.), then runs the editable install with `--no-deps` so pip never tries to re-resolve `openwakeword`'s declared transitive deps.

## Config

Everything tunable lives in [`config/buggsy.yaml`](config/buggsy.yaml). Both robot and server load it; missing fields fall back to defaults; env vars override individual fields. The file is sectioned by which side reads what.

## Verifying the scaffold

```python
from shared.protocol import WakeDetector, TTS, GreetingSource  # noqa: F401
```

Should import cleanly with no errors.
