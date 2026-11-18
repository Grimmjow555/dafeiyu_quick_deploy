#!/usr/bin/env bash
# 关闭大肥鱼：先停 QQ 掉线守护（避免它在停机过程中把容器再拉起来），再优雅停止 NapCat、AstrBot。
# 默认保留 data/、napcat/ 与 QQ 登录状态；下次执行 sudo bash start.sh 恢复。
# 用法：sudo bash stop.sh [--down] [--timeout 秒数] [--dry-run]
set -Eeuo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
umask 077

WATCHDOG_UNIT=dafeiyu-qq-watchdog.service
remove_containers=0
dry_run=0
stop_timeout=${STOP_TIMEOUT:-60}
original_args=("$@")

die() { printf '%s\n' "$*" >&2; exit 1; }
trap 'printf "\n关闭在第 %s 行停止。容器可能只停了一半，重跑 sudo bash stop.sh 即可继续。\n" "$LINENO" >&2' ERR

usage() {
  cat <<'EOF'
用法：sudo bash stop.sh [选项]

关闭大肥鱼：先停 QQ 掉线守护（dafeiyu-qq-watchdog），再停 NapCat（QQ 连接），最后停 AstrBot，
让数据写完后再退出。默认只停止容器，data/、napcat/ 和 QQ 登录状态都会保留。
若只想重启容器，请使用 docker compose restart；本脚本会停止守护进程直到下次 start.sh。

选项：
  -d, --down        停止并移除容器；数据目录不受影响，下次 start.sh 会重新创建
      --timeout N   等待优雅退出的秒数，默认 60
      --dry-run     只打印将要执行的操作，不做任何改动
  -h, --help        显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -d|--down) remove_containers=1 ;;
    --timeout)
      [[ $# -ge 2 ]] || die '--timeout 需要一个秒数，例如 --timeout 120。'
      stop_timeout=$2
      shift
      ;;
    --dry-run) dry_run=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "未知参数：$1" ;;
  esac
  shift
done

[[ $stop_timeout =~ ^[0-9]+$ ]] || die '--timeout 必须是非负整数秒。'

[[ ${EUID} -eq 0 ]] || exec sudo -- bash "$0" "${original_args[@]}"

command -v docker >/dev/null 2>&1 || die '未找到 docker：请先执行 sudo bash deploy.sh 完成首次部署。'
docker compose version >/dev/null 2>&1 || die '未找到 docker compose 插件：请先执行 sudo bash deploy.sh。'
[[ -f compose.yaml ]] || die "当前目录缺少 compose.yaml：$PWD"

watchdog_installed() {
  [[ -f "/etc/systemd/system/${WATCHDOG_UNIT}" ]] || systemctl cat "$WATCHDOG_UNIT" >/dev/null 2>&1
}

stop_watchdog() {
  if ! watchdog_installed; then
    printf '未安装 QQ 掉线守护，跳过。\n'
    return 0
  fi
  local state
  state=$(systemctl is-active "$WATCHDOG_UNIT" 2>/dev/null || true)
  if [[ $state != active ]]; then
    printf 'QQ 掉线守护当前未运行（%s），跳过。\n' "${state:-unknown}"
    return 0
  fi
  if [[ $dry_run -eq 1 ]]; then
    printf '(dry-run) 将停止 QQ 掉线守护（%s）\n' "$WATCHDOG_UNIT"
    return 0
  fi
  printf '停止 QQ 掉线守护（先停它，避免停机过程中把容器再拉起来）…\n'
  systemctl stop "$WATCHDOG_UNIT" || die "停止 QQ 掉线守护失败：请查看 systemctl status ${WATCHDOG_UNIT}。"
  for ((i = 0; i < 15; i++)); do
    state=$(systemctl is-active "$WATCHDOG_UNIT" 2>/dev/null || true)
    [[ $state != active ]] && return 0
    sleep 1
  done
  die 'QQ 掉线守护未在 15 秒内停止，请重试 sudo bash stop.sh。'
}

stop_watchdog

if ! docker info >/dev/null 2>&1; then
  printf 'Docker 服务未运行，大肥鱼容器已处于停止状态。\n'
  if [[ $dry_run -eq 1 ]]; then
    printf '(dry-run) 未做任何改动。\n'
  else
    printf 'QQ 掉线守护已停止；下次执行 sudo bash start.sh 会重新启动它。\n'
  fi
  exit 0
fi

containers=$(docker compose ps -a -q 2>/dev/null || true)
if [[ -z $containers ]]; then
  printf '大肥鱼当前没有容器，已经是停止状态。\n'
  if [[ $dry_run -eq 1 ]]; then
    printf '(dry-run) 未做任何改动。\n'
  else
    printf 'QQ 掉线守护已停止；下次执行 sudo bash start.sh 会重新启动容器和守护进程。\n'
  fi
  exit 0
fi

stop_service() {
  local service=$1 label=$2
  if [[ -n $(docker compose ps -a -q "$service" 2>/dev/null || true) ]]; then
    if [[ $dry_run -eq 1 ]]; then
      printf '(dry-run) 将停止 %s（%s）\n' "$label" "$service"
    else
      printf '停止 %s…\n' "$label"
      docker compose stop --timeout "$stop_timeout" "$service"
    fi
  fi
}

stop_service napcat NapCat
stop_service astrbot AstrBot

if [[ $remove_containers -eq 1 ]]; then
  if [[ $dry_run -eq 1 ]]; then
    printf '(dry-run) 将移除容器（docker compose down --timeout %s）\n' "$stop_timeout"
  else
    printf '移除容器…\n'
    docker compose down --timeout "$stop_timeout"
  fi
fi

if [[ $dry_run -eq 1 ]]; then
  printf '\n(dry-run) 未做任何改动。\n'
  exit 0
fi

running=$(docker compose ps --services --status running 2>/dev/null || true)
[[ -z $running ]] || die "仍有服务在运行：${running}。请重跑 sudo bash stop.sh。"

docker compose ps -a
printf '\n大肥鱼已停止。\n'
if [[ $remove_containers -eq 1 ]]; then
  printf '容器已移除，data/、napcat/ 未改动，下次执行 sudo bash start.sh 会重新创建。\n'
else
  printf '数据与 QQ 登录状态已保留，下次执行 sudo bash start.sh 恢复。\n'
fi
printf 'QQ 掉线守护已停止，下次 start.sh 会重新启动它。\n'
printf '手动停止的容器不会因服务器重启而自动拉起。\n'
