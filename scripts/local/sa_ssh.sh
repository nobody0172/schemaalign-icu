#!/usr/bin/env bash
# SchemaAlign-ICU 远程执行工具
#
# 用法:
#   scripts/local/sa_ssh.sh run   "<remote shell command>"    # 执行远程命令
#   scripts/local/sa_ssh.sh put   <local_path> <remote_path>  # 上传
#   scripts/local/sa_ssh.sh get   <remote_path> <local_path>  # 下载
#   scripts/local/sa_ssh.sh pyrun <local_py> [args...]        # 上传并用远端 venv 执行 py
#
# 所有 run/pyrun 的 stdout+stderr 同时落盘到 logs/ssh/<timestamp>_<tag>.log
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${HERE}/.secrets/server.env"

SSHOPT=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
        -o LogLevel=ERROR -o ServerAliveInterval=30 -o ServerAliveCountMax=240)
LOGDIR="${HERE}/logs/ssh"
mkdir -p "$LOGDIR"
TS="$(date +%Y%m%d_%H%M%S)"

_ssh() { SSHPASS="$SA_SSH_PASS" sshpass -e ssh "${SSHOPT[@]}" -p "$SA_SSH_PORT" "${SA_SSH_USER}@${SA_SSH_HOST}" "$@"; }
_scp() { SSHPASS="$SA_SSH_PASS" sshpass -e scp "${SSHOPT[@]}" -P "$SA_SSH_PORT" "$@"; }

cmd="${1:?usage: run|put|get|pyrun}"; shift

case "$cmd" in
  run)
    TAG="${SA_TAG:-run}"
    LOG="${LOGDIR}/${TS}_${TAG}.log"
    { echo "### CMD: $*"; echo "### AT : $(date -u +%FT%TZ)"; echo "### ---"; } | tee "$LOG"
    _ssh "$@" 2>&1 | tee -a "$LOG"
    echo "[sa_ssh] log -> ${LOG#$HERE/}" >&2
    ;;
  put)
    _scp -r "$1" "${SA_SSH_USER}@${SA_SSH_HOST}:$2"
    ;;
  get)
    _scp -r "${SA_SSH_USER}@${SA_SSH_HOST}:$1" "$2"
    ;;
  pyrun)
    LOCAL_PY="$1"; shift
    BASE="$(basename "$LOCAL_PY")"
    TAG="${SA_TAG:-${BASE%.py}}"
    LOG="${LOGDIR}/${TS}_${TAG}.log"
    _ssh "mkdir -p ${SA_REMOTE_PROJECT}/src/remote_jobs"
    _scp "$LOCAL_PY" "${SA_SSH_USER}@${SA_SSH_HOST}:${SA_REMOTE_PROJECT}/src/remote_jobs/${BASE}"
    { echo "### PY  : ${BASE} $*"; echo "### AT  : $(date -u +%FT%TZ)"; echo "### ---"; } | tee "$LOG"
    _ssh "cd ${SA_REMOTE_PROJECT} && ${SA_REMOTE_PY} src/remote_jobs/${BASE} $*" 2>&1 | tee -a "$LOG"
    echo "[sa_ssh] log -> ${LOG#$HERE/}" >&2
    ;;
  *) echo "unknown: $cmd" >&2; exit 2;;
esac
