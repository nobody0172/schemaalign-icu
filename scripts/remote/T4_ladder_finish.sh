#!/usr/bin/env bash
# T4 编码器阶梯 —— 补齐 bge_large 与 qwen15 两档
#
# 背景: 2026-08-18 首轮运行时 bge_large 在 1.33GB/1.34GB 处
#       IncompleteRead 断流, qwen15 因此未被执行 (仅下到 41MB/3.09GB)。
#       实测直连 huggingface.co < 1MB/s (含 AutoDL 学术加速), hf-mirror.com 3.3MB/s 且支持 Range。
#
# 输入: 无 (断点续传自 ~/.cache/huggingface/hub 下的 .incomplete blob)
# 输出: outputs/T4_ladder/{bge_large,qwen15}_*.npy , outputs/table3_encoder_ladder.csv
#       全量日志 logs/T4_ladder_finish.log  (C7)
set -uo pipefail
P=/root/autodl-tmp/projects/SchemaAlign-ICU
PY=/root/autodl-tmp/envs/sa/bin/python
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_ENABLE_HF_TRANSFER=0

echo "=== [$(date -u +%FT%TZ)] 阶段 1/3: 断点续传模型权重 (endpoint=$HF_ENDPOINT) ==="
for i in 1 2 3 4 5; do
  $PY - <<'PYEOF'
import os, sys
from huggingface_hub import snapshot_download
ok = True
for repo in ["BAAI/bge-large-en-v1.5", "Qwen/Qwen2.5-1.5B"]:
    try:
        p = snapshot_download(repo, allow_patterns=["*.json","*.txt","*.safetensors","*.model"],
                              max_workers=2)
        print("[dl-ok] %s -> %s" % (repo, p), flush=True)
    except Exception as e:
        ok = False
        print("[dl-err] %s %s" % (repo, str(e)[:200]), flush=True)
sys.exit(0 if ok else 7)
PYEOF
  [ $? -eq 0 ] && { echo "[dl] 全部就绪 (第 $i 次尝试)"; break; }
  echo "[dl] 第 $i 次未完成, 15s 后续传"; sleep 15
done

echo "=== [$(date -u +%FT%TZ)] 阶段 2/3: 编码 ==="
cd "$P" || exit 1
$PY src/T4_encoder_ladder.py --only bge_large,qwen15 --batch 32 --gpu-frac 0.33

echo "=== [$(date -u +%FT%TZ)] 阶段 3/3: 重算阶梯表 ==="
$PY src/T4_ladder_eval.py

echo "=== [$(date -u +%FT%TZ)] 完成 ==="
