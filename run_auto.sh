#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_python="$task_root/.venv/bin/python"
task_packages=$("$task_python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
task_cuda_libraries="$task_packages/nvidia/cublas/lib:$task_packages/nvidia/cudnn/lib:$task_packages/nvidia/cuda_nvrtc/lib"
exec env LD_LIBRARY_PATH="$task_cuda_libraries:${LD_LIBRARY_PATH:-}" "$task_python" "$task_root/auto_guide.py" "$@"
