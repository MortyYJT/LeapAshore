#!/bin/zsh

# OfferPilot 本地一键启动器（macOS）
# 可以复制到桌面后双击运行；项目代码仍从下面的固定目录读取。

set -u

export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

PROJECT_DIR="~/Documents/留学agent/web"
SITE_URL="http://localhost:8080"
HEALTH_URL="$SITE_URL/api/health/readiness"

pause_on_error() {
  print ""
  print "启动失败。上面是错误信息，请截图发给 Codex。"
  print -n "按回车键关闭窗口……"
  read -r
  exit 1
}

trap pause_on_error ERR

print "========================================"
print "  OfferPilot 本地环境一键启动"
print "========================================"

if [[ ! -d "$PROJECT_DIR" || ! -f "$PROJECT_DIR/compose.yaml" ]]; then
  print "找不到项目目录：$PROJECT_DIR"
  print "如果你移动过项目，请让 Codex 更新启动器里的 PROJECT_DIR。"
  false
fi

if ! command -v docker >/dev/null 2>&1; then
  print "没有找到 Docker。请先安装并打开 Docker Desktop："
  print "https://www.docker.com/products/docker-desktop/"
  false
fi

if ! docker info >/dev/null 2>&1; then
  print "Docker Desktop 还没运行，正在自动打开……"
  open -a Docker

  docker_ready=false
  for attempt in {1..60}; do
    if docker info >/dev/null 2>&1; then
      docker_ready=true
      break
    fi
    sleep 2
  done

  if [[ "$docker_ready" != "true" ]]; then
    print "等待 Docker Desktop 超时，请确认它已经成功启动。"
    false
  fi
fi

cd "$PROJECT_DIR"

print "Docker 已就绪，正在构建并启动网站……"
print "第一次运行会下载依赖，可能需要几分钟；以后会快很多。"

if ! docker compose up -d --build; then
  print "容器构建或启动失败，最近日志如下："
  docker compose logs --tail=80 || true
  false
fi

print "服务已启动，正在等待网站通过健康检查……"

site_ready=false
for attempt in {1..60}; do
  status_code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null || true)"
  if [[ "$status_code" == "200" ]]; then
    site_ready=true
    break
  fi
  sleep 2
done

if [[ "$site_ready" != "true" ]]; then
  print "网站没有在两分钟内准备完成，最近日志如下："
  docker compose logs --tail=80 || true
  false
fi

print ""
print "OfferPilot 已启动：$SITE_URL"
print "正在为你打开浏览器……"
open "$SITE_URL"

osascript -e 'display notification "网站已在 http://localhost:8080 运行" with title "OfferPilot 启动成功"' >/dev/null 2>&1 || true

print "完成。关闭这个终端窗口不会关闭网站。"
sleep 2
