# Buggsy

Buggsy is an office assistant robot built on the [Reachy Mini Wireless](https://github.com/pollen-robotics/reachy_mini). It's the persona for a team of AI agents.

The v1 feature is wake-word detection plus a spoken greeting — see [issue #1](https://github.com/danbiagini/buggsy/issues/1) for the full design and child issues.

## Layout

```
robot/    # runs on the Reachy Mini (Pi CM4)
server/   # orchestrator, TTS, and config services (Ubuntu + GPU)
shared/   # protocol interfaces and MQTT message schemas (used by both)
docs/
```

## Development install

Python 3.12 is required (matches the Reachy Mini SDK).

From the repo root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e shared/ -e robot/ -e server/
```

Install `shared/` first if you install packages individually — `robot/` and `server/` depend on it.

## Verifying the scaffold

```python
from shared.protocol import WakeDetector, TTS, GreetingSource  # noqa: F401
```

Should import cleanly with no errors.
