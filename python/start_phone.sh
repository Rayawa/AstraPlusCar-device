#!/usr/bin/env bash
set -euo pipefail

CAR_DIR=/home/HwHiAiUser/E2E-Samples-ziyan/src/E2E-Sample/Car/python
cd "$CAR_DIR"
# Vendor environment scripts may read unset variables.
set +u
source /usr/local/Ascend/ascend-toolkit/set_env.sh
source /home/HwHiAiUser/pyorbbecsdk/env.sh
set -u
export PYTHONPATH="/home/HwHiAiUser/pyorbbecsdk/install/lib${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/local/miniconda3/bin/python main.py --mode phone "$@"
