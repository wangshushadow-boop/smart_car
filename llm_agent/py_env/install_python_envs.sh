#!/usr/bin/env bash
# 创建 Agent 使用的全部隔离 Python 环境，并下载本地模型。
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
env_dir="${root}/llm_agent/py_env"
venv_dir="${env_dir}/venvs"
model_dir="${CAR_MODEL_DIR:-/mnt/d/AI/models}"
python="${CAR_PYTHON:-python3.12}"
pip_source="${CAR_PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1

for command_name in "${python}" curl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Missing command: ${command_name}" >&2
    exit 1
  }
done

install_env() {
  local name="$1"
  local venv="${venv_dir}/${name}"
  local requirements="${env_dir}/requirements-${name}.txt"
  [[ -x "${venv}/bin/python" ]] || "${python}" -m venv "${venv}"
  "${venv}/bin/python" -m pip install -U pip -i "${pip_source}"
  "${venv}/bin/python" -m pip install -r "${requirements}" -i "${pip_source}"
}

mkdir -p "${venv_dir}" "${model_dir}"
for name in agent minicpm qwen3-asr ros2-trace; do
  install_env "${name}"
done

[[ -f "${model_dir}/MiniCPM-o-4_5-AWQ/config.json" ]] || \
  "${venv_dir}/minicpm/bin/modelscope" download --model OpenBMB/MiniCPM-o-4_5-AWQ \
    --local_dir "${model_dir}/MiniCPM-o-4_5-AWQ"
[[ -f "${model_dir}/Qwen3-ASR-0.6B/config.json" ]] || \
  "${venv_dir}/qwen3-asr/bin/modelscope" download --model Qwen/Qwen3-ASR-0.6B \
    --local_dir "${model_dir}/Qwen3-ASR-0.6B"

voice_dir="${model_dir}/piper/zh_CN-huayan-medium"
voice_url="${HF_ENDPOINT}/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium"
mkdir -p "${voice_dir}"
for file in zh_CN-huayan-medium.onnx zh_CN-huayan-medium.onnx.json; do
  [[ -s "${voice_dir}/${file}" ]] || curl -L --fail --retry 3 \
    -o "${voice_dir}/${file}" "${voice_url}/${file}"
done

"${venv_dir}/agent/bin/python" -c "import langgraph, openai, pydantic, yaml"
"${venv_dir}/minicpm/bin/python" -c "import vllm, vllm_omni"
"${venv_dir}/minicpm/bin/vllm" --help >/dev/null
"${venv_dir}/qwen3-asr/bin/python" -c "import qwen_asr"
"${venv_dir}/ros2-trace/bin/python" -c "import bokeh, pandas, pyarrow"

echo "Python environments installed in ${venv_dir}"
echo "Models installed in ${model_dir}"
