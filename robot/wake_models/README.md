# Wake-word models

openWakeWord `.onnx` model files live here. They are gitignored — download
them out-of-band.

## Quickstart: pretrained models

openWakeWord ships several pretrained models. Download them all into this
directory:

```bash
python -c "import openwakeword.utils; openwakeword.utils.download_models()"
```

The default model used by the dev smoke test is `hey_jarvis_v0.1.onnx`. Once
downloaded (location depends on your install — copy or symlink it here, or
set `BUGGSY_WAKE_MODEL=/full/path/to/model.onnx`), you can run:

```bash
python -m robot.agent.dev_smoke
```

## Custom "Buggsy" model

Planned for a later iteration — train from synthetic TTS samples. Tracked
separately.
