#!/usr/bin/env bash
# Install the independent Chinese Piper TTS backend in the shared MiniCPM venv.
set -euo pipefail

venv_python="${MINICPM_PYTHON:-/opt/minicpm-service/venv/bin/python}"
voice_dir="${CAR_TTS_VOICE_DIR:-${HOME}/.local/share/piper/zh_CN-huayan-medium}"
model_name="zh_CN-huayan-medium"
model_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium"

"${venv_python}" -m pip install --no-deps \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple piper-tts pathvalidate

mkdir -p "${voice_dir}"
for filename in "${model_name}.onnx" "${model_name}.onnx.json"; do
  if [[ ! -s "${voice_dir}/${filename}" ]]; then
    curl -L --fail --retry 3 -o "${voice_dir}/${filename}" "${model_url}/${filename}"
  fi
done

printf '%s' '你好，小车语音测试。' | "${venv_python}" -m piper \
  --model "${voice_dir}/${model_name}.onnx" \
  --config "${voice_dir}/${model_name}.onnx.json" \
  --output-file /tmp/piper_tts_check.wav
file /tmp/piper_tts_check.wav
