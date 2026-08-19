#!/usr/bin/env bash
# SchemaAlign-ICU 资源护栏 —— 与同机 RewardProg-ICU 共存
#
# 机器: 16 vCPU / 80 GiB / RTX 4090D 24 GB / 数据盘 350 GB (与 RewardProg 共享)
#
# 预算 (只占一半, 另一半留给 RewardProg):
#   CPU   8 / 16 线程
#   内存  24 / 80 GiB   (duckdb memory_limit)
#   显存  8 / 24 GiB    (torch per-process fraction)
#   磁盘  25 GB 上限, 全部落在 projects/SchemaAlign-ICU 之内
#
# 用法:
#   source sa_guard.sh              # 导出预算环境变量
#   sa_guard.sh check               # 打印当前占用, 判断是否可以起新作业
#   sa_guard.sh check --gpu         # 额外要求 GPU 有足够空闲显存
#   sa_guard.sh run <cmd...>        # 以 nice+ionice 在预算内跑

export SA_CPU_BUDGET=8
export SA_MEM_BUDGET_GB=24
export SA_GPU_BUDGET_GB=8
export SA_DISK_BUDGET_GB=25
export SA_PROJECT=/root/autodl-tmp/projects/SchemaAlign-ICU

# duckdb / BLAS 线程上限, 所有远程作业都应继承
export SA_DUCKDB_THREADS=$SA_CPU_BUDGET
export SA_DUCKDB_MEMLIMIT="${SA_MEM_BUDGET_GB}GB"
export OMP_NUM_THREADS=$SA_CPU_BUDGET
export MKL_NUM_THREADS=$SA_CPU_BUDGET
export OPENBLAS_NUM_THREADS=$SA_CPU_BUDGET
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:256

_gpu_free_mib() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1; }
_gpu_procs()    { nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . ; }
_load1()        { awk '{print $1}' /proc/loadavg; }
_mem_used_gb()  { echo $(( $(cat /sys/fs/cgroup/memory.current) / 1073741824 )); }
_disk_free_gb() { df -BG --output=avail /root/autodl-tmp | tail -1 | tr -dc '0-9'; }
_sa_disk_gb()   { du -sBG "$SA_PROJECT" 2>/dev/null | cut -f1 | tr -dc '0-9'; }

sa_check() {
  local need_gpu="${1:-}" rc=0
  local gfree gproc mem dfree sdisk
  gfree=$(_gpu_free_mib); gproc=$(_gpu_procs); mem=$(_mem_used_gb)
  dfree=$(_disk_free_gb); sdisk=$(_sa_disk_gb)
  echo "── SchemaAlign-ICU 资源护栏 ──────────────────────────"
  printf "  CPU 预算      %2d / 16 线程        当前 load1 = %s\n" "$SA_CPU_BUDGET" "$(_load1)"
  printf "  内存预算      %2d / 80 GiB         容器已用 = %s GiB\n" "$SA_MEM_BUDGET_GB" "$mem"
  printf "  显存预算       %2d / 24 GiB         GPU 空闲 = %s MiB, 计算进程 = %s\n" "$SA_GPU_BUDGET_GB" "$gfree" "$gproc"
  printf "  磁盘预算      %2d GB               本项目已用 = %s GB, 盘剩余 = %s GB\n" "$SA_DISK_BUDGET_GB" "$sdisk" "$dfree"

  if [ "$gproc" -gt 0 ]; then
    echo "  ⚠ GPU 上有其它计算进程 (很可能是 RewardProg-ICU)"
  fi
  if [ -n "$need_gpu" ]; then
    if [ "${gfree:-0}" -lt $((SA_GPU_BUDGET_GB * 1024 + 2048)) ]; then
      echo "  ✗ GPU 空闲显存不足 ${SA_GPU_BUDGET_GB}GB + 2GB 余量 -> 应推迟 GPU 作业或退回 CPU"; rc=1
    fi
  fi
  if [ "${dfree:-0}" -lt 40 ]; then
    echo "  ✗ 盘剩余 < 40 GB -> 先清理再跑 (可回收: mimic/*.zip 共 23.4 GB, 需先征得同意)"; rc=1
  fi
  if [ "${sdisk:-0}" -gt "$SA_DISK_BUDGET_GB" ]; then
    echo "  ✗ 本项目已超 ${SA_DISK_BUDGET_GB}GB 磁盘预算"; rc=1
  fi
  [ $rc -eq 0 ] && echo "  ✓ 可以起新作业"
  echo "──────────────────────────────────────────────────────"
  return $rc
}

sa_run() {
  sa_check || { echo "[guard] 预算检查未通过, 拒绝启动"; return 1; }
  echo "[guard] nice 10 / ionice best-effort 7 / threads=$SA_CPU_BUDGET"
  nice -n 10 ionice -c 2 -n 7 "$@"
}

case "${1:-}" in
  check) shift; sa_check "$@" ;;
  run)   shift; sa_run "$@" ;;
  "")    : ;;                      # 被 source 时只导出变量
  *)     echo "用法: sa_guard.sh [check [--gpu] | run <cmd...>]" >&2; exit 2 ;;
esac
