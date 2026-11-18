#!/usr/bin/env bash
# 启动大肥鱼：在本目录用 Docker Compose 拉起 AstrBot、NapCat，并启动 QQ 掉线守护进程。
# 首次安装/更新仍用 upload.ps1 或 deploy.sh；本脚本只负责启停现有服务，不联网拉镜像、不改配置。
# 用法：sudo bash start.sh [--no-wait] [--status]
set -Eeuo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
umask 077

ASTRBOT_PORT=6185
NAPCAT_PORT=6099
WATCHDOG_UNIT=dafeiyu-qq-watchdog.service
CONTAINER_WAIT=120
PORT_WAIT=90
wait_ready=1
status_only=0
ports_ready=0
watchdog_ready=0
original_args=("$@")

die() { printf '%s\n' "$*" >&2; exit 1; }
trap 'printf "\n启动在第 %s 行停止。用 docker compose logs --tail=50 查看原因后重试。\n" "$LINENO" >&2' ERR

usage() {
  cat <<'EOF'
用法：sudo bash start.sh [选项]

启动大肥鱼（AstrBot + NapCat），并启动已安装的 QQ 掉线守护进程（dafeiyu-qq-watchdog）。
只拉起已有容器，不重新安装、不联网拉取镜像；data/、napcat/ 中的配置与 QQ 登录状态不变。

选项：
  --no-wait   启动后不等待后台端口就绪
  --status    只显示当前状态（容器、守护进程、QQ 登录），不做任何改动
  -h, --help  显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-wait) wait_ready=0 ;;
    --status) status_only=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "未知参数：$1" ;;
  esac
  shift
done

[[ ${EUID} -eq 0 ]] || exec sudo -- bash "$0" "${original_args[@]}"

command -v docker >/dev/null 2>&1 || die '未找到 docker：请先执行 sudo bash deploy.sh 完成首次部署。'
docker compose version >/dev/null 2>&1 || die '未找到 docker compose 插件：请先执行 sudo bash deploy.sh。'
[[ -f compose.yaml ]] || die "当前目录缺少 compose.yaml：$PWD"

if ! docker info >/dev/null 2>&1; then
  printf 'Docker 服务未运行，正在启动…\n'
  systemctl start docker || die 'Docker 服务启动失败：请检查 systemctl status docker。'
  for ((i = 0; i < 30; i++)); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
  docker info >/dev/null 2>&1 || die 'Docker 服务启动后仍无响应。'
fi

watchdog_installed() {
  [[ -f "/etc/systemd/system/${WATCHDOG_UNIT}" ]] || systemctl cat "$WATCHDOG_UNIT" >/dev/null 2>&1
}

watchdog_state() {
  if watchdog_installed; then
    systemctl is-active "$WATCHDOG_UNIT" 2>/dev/null || true
  else
    printf '未安装'
  fi
}

qq_status_line() {
  if [[ -f qq_watchdog.py ]] && command -v python3 >/dev/null 2>&1; then
    if watchdog_installed; then
      printf '\nQQ / 守护进程状态：\n'
      python3 qq_watchdog.py --status 2>&1 | sed 's/^/  /' || true
    fi
  fi
}

if [[ $status_only -eq 1 ]]; then
  docker compose ps
  printf '\nQQ 掉线守护：%s\n' "$(watchdog_state)"
  if [[ -n $(docker compose ps --services --status running 2>/dev/null) ]]; then
    qq_status_line
    printf '\n大肥鱼正在运行。\n'
    exit 0
  fi
  printf '\n大肥鱼当前未运行，可执行 sudo bash start.sh 启动。\n'
  exit 1
fi

[[ -f .env ]] || die '缺少 .env：QQ 设备标识无法重建，请执行 sudo bash deploy.sh 重新初始化，不要删除 napcat/ 或 data/。'

images=$(docker compose config --images 2>/dev/null) || die 'compose.yaml 解析失败：请检查 .env 与 compose.yaml。'
[[ -n $images ]] || die 'compose.yaml 未解析出任何镜像。'
for image in $images; do
  docker image inspect "$image" >/dev/null 2>&1 ||
    die "镜像不存在：${image}。请先执行 sudo bash deploy.sh 下载，再回来启动。"
done

printf '启动 AstrBot 与 NapCat…\n'
up_help=$(docker compose up --help 2>/dev/null || true)
if [[ $up_help == *--pull* ]]; then
  docker compose up -d --pull never
else
  docker compose up -d
fi

ready=0
for ((i = 0; i < CONTAINER_WAIT / 2; i++)); do
  running=$(docker compose ps --services --status running 2>/dev/null || true)
  if [[ $running == *astrbot* && $running == *napcat* ]]; then
    ready=1
    break
  fi
  sleep 2
done
if [[ $ready -ne 1 ]]; then
  docker compose ps
  die "容器未在 ${CONTAINER_WAIT} 秒内全部运行：请执行 docker compose logs --tail=50 查看原因。"
fi

if watchdog_installed; then
  printf '启动 QQ 掉线守护…\n'
  systemctl enable "$WATCHDOG_UNIT" >/dev/null 2>&1 || true
  if systemctl start "$WATCHDOG_UNIT"; then
    for ((i = 0; i < 20; i++)); do
      if [[ $(systemctl is-active "$WATCHDOG_UNIT" 2>/dev/null) == active ]]; then
        watchdog_ready=1
        break
      fi
      sleep 1
    done
  fi
  if [[ $watchdog_ready -ne 1 ]]; then
    printf '警告：QQ 掉线守护未启动，请执行 journalctl -u %s -n 50 查看原因。\n' "$WATCHDOG_UNIT" >&2
  fi
else
  printf '提示：未安装 QQ 掉线守护（%s）；需要掉线自动恢复时请先执行 sudo bash deploy.sh。\n' "$WATCHDOG_UNIT"
fi

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

if [[ $wait_ready -eq 1 ]]; then
  printf '等待后台端口就绪…\n'
  for ((i = 0; i < PORT_WAIT / 2; i++)); do
    if port_open "$ASTRBOT_PORT" && port_open "$NAPCAT_PORT"; then
      ports_ready=1
      break
    fi
    sleep 2
  done
fi

docker compose ps
if [[ $wait_ready -eq 0 ]]; then
  printf '\n容器与守护进程已启动（已跳过就绪等待）。\n'
elif [[ $ports_ready -eq 1 ]]; then
  printf '\n大肥鱼已启动。\n'
else
  printf '\n容器已启动，后台端口仍在初始化；稍后用 sudo bash start.sh --status 确认。\n'
fi
printf 'QQ 掉线守护：%s\n' "$(watchdog_state)"

host=
if [[ -f key.txt ]]; then
  host=$(awk -F= '/^SSH_HOST=/ { print $2; exit }' key.txt 2>/dev/null | tr -d '\r')
fi
if [[ -n $host ]]; then
  printf '  AstrBot: http://%s:%s/\n' "$host" "$ASTRBOT_PORT"
  printf '  NapCat : http://%s:%s/webui/web_login\n' "$host" "$NAPCAT_PORT"
fi
qq_status_line
printf '若 QQ 显示离线，请在 NapCat 后台刷新二维码后重新扫码；已配置密码兜底时守护进程会先尝试自动恢复。\n'
