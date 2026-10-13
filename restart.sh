#!/usr/bin/env bash
# 先快进拉取当前分支的远端，再停掉本仓库的 API 和决策地图并重新启动。
# 拉取失败不停进程。只能快进，不合并、不覆盖本地修改。
# 拉完会重新执行本脚本：git 可能刚改写了这个文件，后半段必须跑新副本。
# API 不使用 --reload：只有新进程才会重新 import 已加载的 Python 模块。
# 内存里的任务不落盘，重启后清空。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT=8010
WEB_PORT=5176
LOG_DIR="$ROOT/outputs/dev-servers"
targets=()

die() { echo "$*" >&2; exit 1; }

resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    [[ -x "$PYTHON" ]] || die "PYTHON 不可执行: $PYTHON"
    return
  fi
  command -v conda >/dev/null 2>&1 || die "找不到 conda。请设置 PYTHON 为 torch311 的 python。"
  local base
  base="$(conda info --base)"
  PYTHON="$base/envs/torch311/bin/python"
  [[ -x "$PYTHON" ]] || die "找不到 torch311: $PYTHON"
}

ensure_npm() {
  if command -v npm >/dev/null 2>&1; then
    return
  fi
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    source "$HOME/.nvm/nvm.sh"
  fi
  command -v npm >/dev/null 2>&1 || die "找不到 npm。"
}

belongs_here() {
  local pid=$1 cwd cmd
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cwd" == "$ROOT" || "$cwd" == "$ROOT/"* || "$cmd" == *"$ROOT"* ]]
}

port_pids() {
  local port=$1
  ss -ltnp "sport = :$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
}

add_target() {
  local pid=$1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ -d "/proc/$pid" ]] || return 0
  belongs_here "$pid"
}

kill_tree() {
  local pid=$1 child
  [[ -d "/proc/$pid" ]] || return 0
  for child in $(pgrep -P "$pid" || true); do
    kill_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

read_pidfile() {
  local file=$1
  [[ -f "$file" ]] || return 0
  tr -d '[:space:]' < "$file"
}

collect_targets() {
  local pid port cmd
  for pid in "$(read_pidfile "$LOG_DIR/api.pid")" "$(read_pidfile "$LOG_DIR/web.pid")"; do
    [[ -n "$pid" ]] || continue
    if ! add_target "$pid"; then
      die "pid $pid 不属于本仓库，已停止重启。"
    fi
    targets+=("$pid")
  done
  for port in "$API_PORT" "$WEB_PORT"; do
    for pid in $(port_pids "$port"); do
      if ! add_target "$pid"; then
        cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        die "端口 $port 被其他程序占用: pid $pid $cmd"
      fi
      targets+=("$pid")
    done
  done
}

wait_port_free() {
  local port=$1 i
  for i in $(seq 1 20); do
    [[ -z "$(port_pids "$port")" ]] && return 0
    sleep 0.5
  done
  return 1
}

wait_http() {
  local url=$1 i
  for i in $(seq 1 90); do
    if curl -sf --max-time 2 "$url" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

fail_log() {
  local name=$1 file=$2
  echo "$name 没有在 90 秒内就绪。最后日志：" >&2
  tail -n 40 "$file" >&2 || true
  exit 1
}

pull_latest() {
  local before after upstream
  cd "$ROOT"
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "这里不是 git 仓库，无法拉取。软件仍在运行。"
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  [[ -n "$upstream" ]] || die "当前分支没有上游，无法拉取。软件仍在运行。"
  before="$(git rev-parse HEAD)"
  echo "拉取 $upstream"
  if ! GIT_TERMINAL_PROMPT=0 git pull --ff-only; then
    die "拉取失败，软件仍在运行。只接受快进；本地提交和冲突都不会被覆盖。"
  fi
  after="$(git rev-parse HEAD)"
  echo "代码  $(git log -1 --oneline)"
  if [[ "$before" != "$after" ]] && git diff --name-only "$before" "$after" | grep -Eq '^(frontend/package\.json|frontend/package-lock\.json)$'; then
    echo "前端依赖有变化，执行 npm install"
    ensure_npm
    npm install --prefix "$ROOT/frontend" || die "npm install 失败，软件仍在运行。"
  fi
}

if [[ "${RESTART_PULLED:-}" != 1 ]]; then
  pull_latest
  RESTART_PULLED=1 exec "$ROOT/restart.sh"
fi

resolve_python
ensure_npm
mkdir -p "$LOG_DIR"
collect_targets

for pid in "${targets[@]+"${targets[@]}"}"; do
  echo "停止 pid $pid"
  kill_tree "$pid"
done

if ! wait_port_free "$API_PORT" || ! wait_port_free "$WEB_PORT"; then
  for pid in "${targets[@]+"${targets[@]}"}"; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  sleep 0.5
fi
for port in "$API_PORT" "$WEB_PORT"; do
  [[ -z "$(port_pids "$port")" ]] || die "端口 $port 仍被占用。"
done

cd "$ROOT"
nohup "$PYTHON" -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$API_PORT" \
  > "$LOG_DIR/api.log" 2>&1 &
echo $! > "$LOG_DIR/api.pid"

cd "$ROOT/frontend"
nohup npm run dev > "$LOG_DIR/web.log" 2>&1 &
echo $! > "$LOG_DIR/web.pid"

cd "$ROOT"
if ! wait_http "http://127.0.0.1:$API_PORT/api/v1/health"; then
  fail_log "API" "$LOG_DIR/api.log"
fi
if ! wait_http "http://127.0.0.1:$WEB_PORT/"; then
  fail_log "决策地图" "$LOG_DIR/web.log"
fi
if ! wait_http "http://127.0.0.1:$WEB_PORT/api/v1/health"; then
  fail_log "页面到 API 的转发" "$LOG_DIR/web.log"
fi

lan="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "已拉取远端并重新启动。内存中的任务已清空。"
echo "代码  $(git -C "$ROOT" log -1 --oneline)"
echo "目录  $ROOT"
echo "页面  http://127.0.0.1:$WEB_PORT"
if [[ -n "$lan" ]]; then
  echo "局域网 http://$lan:$WEB_PORT"
fi
echo "API   http://127.0.0.1:$API_PORT"
echo "日志  $LOG_DIR/api.log"
echo "      $LOG_DIR/web.log"
