#!/usr/bin/env bash
# Install Buggsy robot dependencies.
#
# Workaround for openwakeword's tflite-runtime requirement: there are no
# tflite-runtime wheels for Python 3.12 / aarch64. We use the ONNX backend
# exclusively, so we install openwakeword with --no-deps first, then let
# the normal editable install pick up everything else.
#
# Usage:
#   ./robot/scripts/install.sh
#   PIP=/venvs/apps_venv/bin/pip ./robot/scripts/install.sh
set -euo pipefail

PIP="${PIP:-pip}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo ">> Installing openwakeword (without tflite-runtime / scikit-learn)..."
"$PIP" install --no-deps "openwakeword>=0.6,<1"

echo ">> Installing the openwakeword deps we actually need (ONNX path)..."
"$PIP" install onnxruntime scipy requests tqdm

echo ">> Installing buggsy-shared and buggsy-robot in editable mode..."
"$PIP" install -e "$REPO_ROOT/shared" -e "$REPO_ROOT/robot"

echo
echo "Done. Verify with:"
echo "  python -m robot.scripts.preflight"
