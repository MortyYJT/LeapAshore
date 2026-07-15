# OfferPilot 封闭 Beta 上线 Runbook

## 1. 上线前资源

- 一台支持 Docker Compose 的 Linux 服务器，建议至少 4 vCPU、8 GB 内存、40 GB SSD。
- 一个已解析到服务器公网 IP 的域名。
- 一个支持 SMTP 的事务邮件账户，用于邮箱验证和密码重置。
- 独立生成的 PostgreSQL 强密码；不要复用面板、SSH 或邮箱密码。
- 管理员邮箱，必须与 `ADMIN_EMAILS` 完全一致。

复制并填写生产配置：

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

生产环境会拒绝以下配置：缺少数据库、SMTP、域名或管理员邮箱；使用 HTTP 的 `APP_URL`；包含 localhost 或通配符的 CORS。

填写完成后先运行发布预检；它会拒绝示例占位值、弱数据库密码、错误域名和无法解析的生产 Compose：

```bash
sh deploy/preflight.sh .env.production
```

在接入真实邮件服务前，先用本地 Mailpit 完成可重复的 SMTP 预验收：

```bash
docker compose -f compose.yaml -f compose.mailpit.yaml up -d --build
api/.venv/bin/python api/evals/email_e2e.py
```

验收脚本必须同时通过验证邮件、密码重置邮件、旧密码失效与新密码登录。

## 2. 首次部署

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml pull
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml up -d --build
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml ps
```

Caddy 会为 `DOMAIN` 自动申请并续期 HTTPS 证书。API 容器每次启动前执行 `alembic upgrade head`，数据库迁移失败时 API 不会带病启动。

## 3. 上线验收

```bash
curl -fsS https://$DOMAIN/api/health
curl -fsS https://$DOMAIN/api/health/readiness
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml logs --tail=100 api gateway
```

人工完成以下流程：

1. 使用管理员邮箱注册，收到验证邮件并完成验证。
2. 登录后确认导航中出现“运营后台”，且用户列表记录了当前服务条款版本。
3. 建立申请背景并生成一次方案。
4. 提交一条产品反馈，在运营后台把状态改为“已解决”。
5. 使用另一个邮箱测试忘记密码，确认旧会话在重置后失效。
6. 下载个人数据导出文件，并用测试账户验证账户删除。

## 4. 备份与恢复

生产 Compose 每天生成 PostgreSQL custom-format 备份，保留 7 天，存放在 `postgres_backups` volume。备份先写入 `.incomplete` 临时文件，只有 `pg_dump` 成功后才原子改名；容器健康检查要求存在 25 小时内生成的完整备份。

手动备份：

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml exec -T postgres \
  pg_dump -U offerpilot -d offerpilot -Fc > offerpilot-manual.dump
```

恢复前应先停止 API 写入，并在独立测试数据库演练。恢复命令：

```bash
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml stop api
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml exec -T postgres \
  pg_restore -U offerpilot -d offerpilot --clean --if-exists < offerpilot-manual.dump
docker compose --env-file .env.production -f compose.yaml -f compose.production.yaml start api
```

每周至少执行一次恢复演练；只有能恢复的备份才算有效备份。

## 5. 运营节奏

- 每天检查运营后台的待处理反馈、注册/验证转化和无结果方向。
- 每周复核高频课程来源与超过 30 天的项目数据。
- 每次发布前运行 `pnpm test`、`pnpm run lint`、`pytest -q`、Agent Eval 和 PostgreSQL 集成测试。
- 第一批只邀请 5–20 名熟人；阻断性问题清零后再扩大。
- 发现安全事件时立即暂停邀请、保留日志、撤销相关会话并轮换基础设施凭据。

## 6. 当前扩容边界

当前限流器适用于单 API 实例的封闭 Beta。扩展到多个 API 副本前，应把限流状态迁移到 Redis，并把文件/成绩单上传迁移到对象存储。Ollama 单实例也需要在扩大用户量前做并发压测和队列控制。
