#!/usr/bin/env bash
# 先快进拉取当前分支的远端，再停掉本仓库的 API 和决策地图并重新启动。
# 拉取失败、工作区不干净、没有上游或 npm install 失败时，不停进程。只能快进。
# 拉完会重新执行本脚本：git 可能刚改写了这个文件，后半段必须跑新副本。
# 停进程时跳过本脚本和它的子进程，所以 API 拉起的这次更新不会把自己杀掉。
# 新进程没有就绪时，退回拉取前的提交再启动。API 不使用 --reload。
# 内存里的任务不落盘，重启后清空。environment.yml 的变化这里不安装。
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT=8010
WEB_PORT=5176
LOG_DIR="$ROOT/outputs/dev-servers"
STATUS_FILE="$LOG_DIR/update-status.json"
targets=()
REFUSE_REASON=""

refuse() {
  write_status failed "$1"
  echo "$1" >&2
  exit 1
}

write_status() {
  local phase=$1 message=$2 commit
  message=${message//\\/\\\\}
  message=${message//\"/\\\"}
  commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || true)"
  mkdir -p "$LOG_DIR"
  printf '%s\n' "{\"id\":\"${UPDATE_ID:-}\",\"phase\":\"$phase\",\"before\":\"${UPDATE_BEFORE:-}\",\"commit\":\"$commit\",\"message\":\"$message\"}" > "$STATUS_FILE"
}

hold_lock() {
  mkdir -p "$LOG_DIR"
  exec 9>"$LOG_DIR/update.lock"
  if ! flock -n 9; then
    echo "已有更新在进行。" >&2
    exit 1
  fi
}

resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    [[ -x "$PYTHON" ]] || refuse "PYTHON 不可执行: $PYTHON"
    return
  fi
  command -v conda >/dev/null 2>&1 || refuse "找不到 conda。请设置 PYTHON 为 torch311 的 python。"
  local base
  base="$(conda info --base)"
  PYTHON="$base/envs/torch311/bin/python"
  [[ -x "$PYTHON" ]] || refuse "找不到 torch311: $PYTHON"
}

ensure_npm() {
  if command -v npm >/dev/null 2>&1; then
    return
  fi
  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    source "$HOME/.nvm/nvm.sh"
  fi
  command -v npm >/dev/null 2>&1 || refuse "找不到 npm。"
}

# 本脚本以及它的子进程。停祖先 API 时不能顺着进程树把更新自己杀掉。
protected_pid() {
  local current=$1
  while [[ "$current" =~ ^[0-9]+$ ]] && [[ "$current" -gt 1 ]]; do
    if [[ "$current" -eq $$ ]]; then
      return 0
    fi
    current="$(awk '/^PPid:/ { print $2 }' "/proc/$current/status" 2>/dev/null || true)"
  done
  return 1
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
  if protected_pid "$pid"; then
    return 0
  fi
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
  targets=()
  REFUSE_REASON=""
  for pid in "$(read_pidfile "$LOG_DIR/api.pid")" "$(read_pidfile "$LOG_DIR/web.pid")"; do
    [[ -n "$pid" ]] || continue
    if ! add_target "$pid"; then
      REFUSE_REASON="pid $pid 不属于本仓库，没有重启。软件仍在运行。"
      return 1
    fi
    targets+=("$pid")
  done
  for port in "$API_PORT" "$WEB_PORT"; do
    for pid in $(port_pids "$port"); do
      if ! add_target "$pid"; then
        cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        REFUSE_REASON="端口 $port 被其他程序占用: pid $pid $cmd"
        return 1
      fi
      targets+=("$pid")
    done
  done
}

ports_free() {
  [[ -z "$(port_pids "$API_PORT")" && -z "$(port_pids "$WEB_PORT")" ]]
}

wait_ports_free() {
  local i
  for i in $(seq 1 20); do
    ports_free && return 0
    sleep 0.5
  done
  return 1
}

stop_listeners() {
  local pid
  if ! collect_targets; then
    return 1
  fi
  for pid in "${targets[@]+"${targets[@]}"}"; do
    echo "停止 pid $pid"
    kill_tree "$pid"
  done
  wait_ports_free && return 0
  for pid in "${targets[@]+"${targets[@]}"}"; do
    protected_pid "$pid" || kill -KILL "$pid" 2>/dev/null || true
  done
  wait_ports_free
}

frontend_deps_changed() {
  ! git -C "$ROOT" diff --quiet "$1" "$2" -- frontend/package.json frontend/package-lock.json
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

healthy() {
  wait_http "http://127.0.0.1:$API_PORT/api/v1/health" \
    && wait_http "http://127.0.0.1:$WEB_PORT/" \
    && wait_http "http://127.0.0.1:$WEB_PORT/api/v1/health"
}

show_log() {
  local name=$1 file=$2
  echo "$name 没有在 90 秒内就绪。最后日志：" >&2
  tail -n 40 "$file" >&2 || true
}

# 关掉 9 号描述符：服务继承了更新锁，脚本退出后锁仍被占着，页面会一直显示正在更新。
detach() {
  local log=$1
  shift
  nohup "$@" >> "$log" 2>&1 9>&- &
}

# 回滚时追加日志，保留新版本失败的那段。
start_servers() {
  if [[ "${1:-}" != append ]]; then
    : > "$LOG_DIR/api.log"
    : > "$LOG_DIR/web.log"
  fi
  cd "$ROOT"
  detach "$LOG_DIR/api.log" "$PYTHON" -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$API_PORT"
  echo $! > "$LOG_DIR/api.pid"
  cd "$ROOT/frontend"
  detach "$LOG_DIR/web.log" npm run dev
  echo $! > "$LOG_DIR/web.pid"
  cd "$ROOT"
}

finish_summary() {
  local lan
  lan="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "代码  $(git -C "$ROOT" log -1 --oneline)"
  echo "目录  $ROOT"
  echo "页面  http://127.0.0.1:$WEB_PORT"
  if [[ -n "$lan" ]]; then
    echo "局域网 http://$lan:$WEB_PORT"
  fi
  echo "API   http://127.0.0.1:$API_PORT"
  echo "日志  $LOG_DIR/api.log"
  echo "      $LOG_DIR/web.log"
}

rollback() {
  echo "新版本没有就绪，正在退回 ${UPDATE_BEFORE:-未知提交}" >&2
  stop_listeners || true
  if [[ -n "${UPDATE_BEFORE:-}" ]]; then
    local pulled
    pulled="$(git -C "$ROOT" rev-parse HEAD)"
    git -C "$ROOT" reset --hard "$UPDATE_BEFORE"
    if frontend_deps_changed "$UPDATE_BEFORE" "$pulled"; then
      npm install --prefix "$ROOT/frontend" || true
    fi
  fi
  start_servers append
  if ! healthy; then
    show_log "退回后的 API" "$LOG_DIR/api.log"
    show_log "退回后的决策地图" "$LOG_DIR/web.log"
    write_status failed "新版本没有就绪，退回后仍没有启动成功。日志在 outputs/dev-servers/。"
    exit 1
  fi
  write_status rolled_back "新版本没有就绪，已退回拉取前的代码并重新启动。内存中的任务已清空。"
  echo "已退回拉取前的代码并重新启动。内存中的任务已清空。"
  finish_summary
  exit 1
}

prepare_pull() {
  local upstream after
  cd "$ROOT"
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || refuse "这里不是 git 仓库，无法拉取。软件仍在运行。"
  [[ -z "$(git status --porcelain)" ]] || refuse "工作区有未提交的修改，已拒绝更新。软件仍在运行。"
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  [[ -n "$upstream" ]] || refuse "当前分支没有上游，无法拉取。软件仍在运行。"
  UPDATE_BEFORE="$(git rev-parse HEAD)"
  export UPDATE_BEFORE
  write_status pulling "正在拉取 $upstream"
  echo "拉取 $upstream"
  if ! GIT_TERMINAL_PROMPT=0 git pull --ff-only; then
    refuse "拉取失败，软件仍在运行。只接受快进；本地提交和冲突都不会被覆盖。"
  fi
  after="$(git rev-parse HEAD)"
  echo "代码  $(git log -1 --oneline)"
  if [[ "$UPDATE_BEFORE" != "$after" ]] && frontend_deps_changed "$UPDATE_BEFORE" "$after"; then
    echo "前端依赖有变化，执行 npm install"
    ensure_npm
    npm install --prefix "$ROOT/frontend" || refuse "npm install 失败，软件仍在运行。"
  fi
}

restart_listeners() {
  resolve_python
  ensure_npm
  [[ -n "${UPDATE_BEFORE:-}" ]] || refuse "缺少拉取前的提交号，没有重启。"
  write_status restarting "正在重启"
  if ! stop_listeners; then
    if [[ -n "$REFUSE_REASON" ]]; then
      refuse "$REFUSE_REASON"
    fi
    rollback
  fi
  start_servers
  if ! healthy; then
    show_log "API" "$LOG_DIR/api.log"
    show_log "决策地图" "$LOG_DIR/web.log"
    rollback
  fi
  write_status succeeded "已拉取远端并重新启动。内存中的任务已清空。"
  echo "已拉取远端并重新启动。内存中的任务已清空。"
  finish_summary
}

main() {
  mkdir -p "$LOG_DIR"
  if [[ "${RESTART_PULLED:-}" != 1 ]]; then
    hold_lock
    export UPDATE_ID="${UPDATE_ID:-$(date +%s)-$$}"
    prepare_pull
    export RESTART_PULLED=1
    exec "$ROOT/restart.sh"
  fi
  if [[ "${SOFTWARE_UPDATE_FROM_API:-}" == 1 ]]; then
    # 给 API 留时间把 202 发回页面，再停掉它。
    sleep 1
  fi
  restart_listeners
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi
