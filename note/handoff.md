# Session handoff

## 当前发布

- PR #91 已合并，合并提交 `30e9131`；发布代码 `a19c8d8`，README/截图提交 `33a4f3a`。
- 线上 https://leapashore.mortyyjt.site 已切换为申请优先的工作台；/applications 支持手动项目、选定轮次、日期/来源及显式自查、状态、材料自查和备注。现有选校组合自动显示，旧 API 保持兼容。
- 首页按日期显示活跃申请，未知日期单列，保留真实路线图勾选；输入问题带入顾问但不自动发送。顾问新增当前申请者个人申请的只读工具。隐私说明同步覆盖个人申请及准备备注。
- README 及 PRD 已统一为硕士申请个人管理工具；桌面/手机截图来自实际正式构建的演示账号。提醒、多轮自动安排、自动提交和材料完整性自动判断尚未实现。
- 验证：859 后端测试、258 前端测试、正式构建、日期/路线图守卫、OpenSpec strict 校验及 183/183 正式构建浏览器检查通过；CI 三项通过；线上 11 项只读检查通过，未在生产写入测试记录。
- Alembic 生产版本 `d1a2b3c4d5e6`，新增 application_plans 表。API、worker、beat、web 已更新；数据库/Redis/Caddy 未重启。旧选校数据未改写。
- 新镜像 deploy-api:application-workspace / deploy-web:application-workspace。回滚镜像各服务 :pre-application-workspace-20261118；数据库备份 ~/db-backup-20261118-application-workspace.dump 已经 pg_restore --list 检查；源码备份 ~/source-backup-20261118-application-workspace.tgz。回滚服务镜像时保留新增表，不运行 downgrade 删除申请记录。
- 本地中断后 Docker 曾退出，已恢复数据库/Redis并完成回归；不要并行运行会重置定义表的 pytest 和浏览器走查。正式预览使用 NEXT_DIST_DIR=.next-workspace-build，端口 3001。

## 用户确认的产品方向与下一步

- 产品定位：帮助硕士申请者管理多个项目的截止日期、材料、任务和申请进度；网页工作台继续保留。
- 下一轮优先「我的申请 + 截止日期管理」：项目、轮次、截止时间、申请状态、材料、官方来源与核查时间；支持手动添加和修改日期。本轮已实现，变更为 openspec/changes/application-workspace。
- 然后让总览按临近截止与待办排序；实际使用后再做提醒。学校库扩充和 AI 新功能优先级降低。
