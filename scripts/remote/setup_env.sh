#!/usr/bin/env bash
# SchemaAlign-ICU 专用 venv —— 与 RewardProg-ICU 完全隔离
#
# 隔离策略:
#   - 落点 /root/autodl-tmp/envs/sa, 不碰 conda base、不碰 /root/mimic-sepsis-venv、
#     不碰 /root/autodl-tmp/rewardprog-icu/python38
#   - 不修改全局 /root/.condarc (其 anaconda/pkgs/free 频道已 404, 但 RewardProg 可能依赖)
#   - 不 source /etc/network_turbo —— 它自己的说明写明「开启后访问 pip 源会更慢」
#
# 为什么用 venv 而非 conda:
#   镜像的 conda 是 4.10.3(2021), tsinghua main 频道解析不出 python>=3.10。
#   而 Python 3.8 足以满足全部依赖: torch 2.4.1 是最后一个支持 3.8 的版本,
#   且其 PyPI 默认 Linux 轮子自带 CUDA 12.1, 原生包含 sm_89 (4090)。
#
# 为什么必须换掉镜像自带的 torch 1.11.0+cu113:
#   torch.cuda.get_arch_list() = [sm_37..sm_86], 不含 sm_89 —— 只能 PTX JIT 回退,
#   无原生内核, cuDNN/cuBLAS 也没有 Ada 调优路径。
set -uo pipefail
ENV=/root/autodl-tmp/envs/sa
BASE_PY=/root/miniconda3/bin/python

echo "[env] $(date -u +%FT%TZ) 创建 venv -> $ENV"
rm -rf "$ENV"; mkdir -p "$(dirname "$ENV")"
$BASE_PY -m venv "$ENV" || { echo "[env] venv 创建失败"; exit 1; }
PIP="$ENV/bin/pip"
$PIP install -q -U pip setuptools wheel 2>&1 | tail -2

echo "[env] torch 2.4.1 (PyPI 默认轮子 = cu121, 含 sm_89)"
nice -n 10 $PIP install --no-cache-dir torch==2.4.1 2>&1 | tail -4

echo "[env] 数据与建模依赖"
nice -n 10 $PIP install --no-cache-dir \
    'duckdb==1.1.3' pandas pyarrow numpy scipy scikit-learn \
    'transformers==4.45.2' 'sentence-transformers==3.1.1' \
    pyyaml pytest tqdm 2>&1 | tail -4

echo "[env] 校验"
"$ENV/bin/python" - <<'PY'
import sys
print("python  ", sys.version.split()[0])
import duckdb, pandas, numpy, sklearn
print("duckdb  ", duckdb.__version__, "| pandas", pandas.__version__,
      "| numpy", numpy.__version__, "| sklearn", sklearn.__version__)
import torch
print("torch   ", torch.__version__, "| built cuda", torch.version.cuda)
print("archs   ", torch.cuda.get_arch_list())
if torch.cuda.is_available():
    cap = torch.cuda.get_device_capability(0)
    tag = "sm_%d%d" % cap
    print("device  ", torch.cuda.get_device_name(0), tag)
    print("原生支持", tag, "?", tag in torch.cuda.get_arch_list())
    a = torch.randn(2048, 2048, device="cuda"); torch.cuda.synchronize()
    print("matmul   OK, sum =", float((a @ a).sum()))
    print("显存占用 %.0f MiB" % (torch.cuda.memory_allocated() / 2**20))
else:
    print("!! CUDA 不可用")
import transformers, sentence_transformers
print("transformers", transformers.__version__,
      "| sentence-transformers", sentence_transformers.__version__)
PY
echo "[env] 体积: $(du -sh $ENV | cut -f1)"
echo "[env] $(date -u +%FT%TZ) 完成。解释器: $ENV/bin/python"
