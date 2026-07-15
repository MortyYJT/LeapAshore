# Security Policy

## Reporting a vulnerability

请不要在公开 Issue 中披露账户绕过、数据泄漏、注入或远程执行问题。请通过仓库所有者公开的安全邮箱私下报告，并附上复现步骤、影响范围和建议修复方式。

## Beta security baseline

- 密码使用 scrypt 加盐哈希保存。
- 会话、邮箱验证和密码重置令牌只保存 SHA-256 哈希，并设置有效期；浏览器会话使用 HttpOnly、SameSite Cookie。
- 邮箱验证和密码重置链接单次使用；重置密码会撤销全部旧会话。
- 管理员接口在 API 层重新校验角色，不依赖前端隐藏。
- 生产配置缺少 PostgreSQL、SMTP、HTTPS 域名或安全 CORS 时拒绝启动。
- 网关和 API 同时设置基础安全响应头；认证接口使用更严格限流。
- 数据库执行版本化迁移和每日备份。

生产上线前仍需完成依赖漏洞扫描、服务器补丁、SSH 加固、防火墙、异地备份和 SMTP 域名的 SPF/DKIM/DMARC 配置。
