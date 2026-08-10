"""隔离环境中的 Qwen3-ASR JSON Lines Worker。"""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout


def main() -> int:
    model = None
    loaded_key = None
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            model_key = (payload["model_path"], payload["device"])
            if model is None or loaded_key != model_key:
                # 第三方库的进度信息不能写入 stdout，否则会破坏 JSONL 协议。
                with redirect_stdout(sys.stderr):
                    import torch
                    from qwen_asr import Qwen3ASRModel

                    model = Qwen3ASRModel.from_pretrained(
                        payload["model_path"],
                        dtype=torch.bfloat16,
                        device_map=payload["device"],
                        max_inference_batch_size=1,
                        max_new_tokens=256,
                    )
                loaded_key = model_key
            language = payload.get("language")
            audio = payload["audio"]
            with redirect_stdout(sys.stderr):
                results = model.transcribe(
                    audio=audio,
                    language=[language] * len(audio) if language else None,
                )
            texts = [str(getattr(result, "text", "")).strip() for result in results]
            text = "\n".join(value for value in texts if value)
            if not text:
                raise RuntimeError("Qwen3 ASR returned empty transcription")
            languages = {
                str(getattr(result, "language", "")).strip()
                for result in results
                if getattr(result, "language", "")
            }
            response = {
                "text": text,
                "language": next(iter(languages)) if len(languages) == 1 else "",
            }
        except Exception as error:
            response = {"error": f"{type(error).__name__}: {error}"}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
