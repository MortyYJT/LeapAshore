#!/bin/sh
set -eu

env_file="${1:-.env.production}"

fail() {
    echo "preflight_failed: $1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "未安装 Docker"
docker compose version >/dev/null 2>&1 || fail "当前 Docker 不支持 Compose"
[ -f "$env_file" ] || fail "找不到 $env_file，请先从 .env.production.example 复制"

read_value() {
    awk -v key="$1" '
        index($0, key "=") == 1 {
            sub(/^[^=]*=/, "")
            print
            exit
        }
    ' "$env_file"
}

for key in DOMAIN POSTGRES_PASSWORD ADMIN_EMAILS SMTP_HOST SMTP_FROM; do
    value="$(read_value "$key")"
    [ -n "$value" ] || fail "$key 未填写"
done

llm_provider="$(read_value LLM_PROVIDER)"
if [ "${llm_provider:-deepseek}" = "deepseek" ]; then
    deepseek_key="$(read_value DEEPSEEK_API_KEY)"
    [ -n "$deepseek_key" ] || fail "LLM_PROVIDER=deepseek 时必须填写 DEEPSEEK_API_KEY"
    case "$deepseek_key" in *replace-with*) fail "DEEPSEEK_API_KEY 仍是示例占位值" ;; esac
fi

domain="$(read_value DOMAIN)"
password="$(read_value POSTGRES_PASSWORD)"
admin_emails="$(read_value ADMIN_EMAILS)"
smtp_host="$(read_value SMTP_HOST)"
smtp_from="$(read_value SMTP_FROM)"

case "$domain" in
    http://*|https://*|*/*|localhost|*.localhost) fail "DOMAIN 只填域名，不要带协议或路径" ;;
esac
[ "${#password}" -ge 32 ] || fail "POSTGRES_PASSWORD 至少需要 32 个字符"
case "$password" in *replace-with*) fail "POSTGRES_PASSWORD 仍是示例占位值" ;; esac
case "$admin_emails" in *example.com*) fail "ADMIN_EMAILS 仍是示例占位值" ;; esac
case "$smtp_host" in smtp.example.com) fail "SMTP_HOST 仍是示例占位值" ;; esac
case "$smtp_from" in *example.com*) fail "SMTP_FROM 仍是示例占位值" ;; esac

docker compose --env-file "$env_file" -f compose.yaml -f compose.production.yaml config >/dev/null
echo "preflight_passed domain=$domain env_file=$env_file"
