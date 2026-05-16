#!/usr/bin/env bash
# Install Buggsy robot dependencies.
#
# Workaround for openwakeword's tflite-runtime requirement: there are no
# tflite-runtime wheels for Python 3.12 / aarch64. We use the ONNX backend
# exclusively, so:
#   1. Install openwakeword with --no-deps.
#   2. Install all buggsy-robot runtime deps ourselves.
#   3. Install the editable packages with --no-deps so pip doesn't try to
#      re-resolve openwakeword's transitive deps.
#
# Usage:
#   ./robot/scripts/install.sh
#   PIP=/venvs/apps_venv/bin/pip ./robot/scripts/install.sh
set -euo pipefail

PIP="${PIP:-pip}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo ">> [1/3] Installing openwakeword without tflite-runtime / scikit-learn..."
"$PIP" install --no-deps "openwakeword>=0.6,<1"

echo
echo ">> [2/3] Installing runtime deps (shared + robot + openwakeword's ONNX path)..."
"$PIP" install \
    "pydantic>=2" \
    "pyyaml>=6" \
    "sounddevice>=0.4" \
    "numpy>=1.26" \
    "scipy>=1.11" \
    "aiomqtt>=2.0" \
    "onnxruntime" \
    "requests" \
    "tqdm"

echo
echo ">> [3/3] Installing buggsy-shared and buggsy-robot in editable mode (no dep re-resolution)..."
"$PIP" install --no-deps -e "$REPO_ROOT/shared" -e "$REPO_ROOT/robot"

echo
echo "Done. Verify with:"
echo "  python -m robot.scripts.preflight"
