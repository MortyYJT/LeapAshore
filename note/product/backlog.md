# 想法池

新想法先落在这里，**不进路线图**，也不开工。只有被用户明确排序、升级的条目才移入 `roadmap.md`。

| 想法 | 来源 | 备注 |
| --- | --- | --- |
| 用临时数据库跑探针，避免崩溃的探针污染共享开发库 | 多次审查反复出现 | 已被两个批次的审查独立提出 |
| 走查的探针脚本进版本库，否则证据不可复现 | M2d 终审 | 现在只存在于 `.runtime-tools/` |
| `test_sources.py` 每次运行泄漏一行 `sources` | 多次审查 | 既有问题，非某个批次引入 |
| 后端测试偶发失败：某行在用例还需要它的时候消失（`applications_client_id_fkey` / `documents_client_id_fkey` / `applications_program_id_fkey` / `roadmap_phases_pkey` 重复） | M3 后端批次 | **既有问题，非 M3 引入**：在 `main` 的 worktree 上、把 M3 的表降级掉之后，单跑 `test_applications_api.py` 六次仍有两次失败。可疑区域是 `conftest` 的清扫与模块级探针 fixture（`test_application_model.py` 自己写的那三个探针项目）之间的相互作用。证据与复现命令记在 `docs/verification/stage-2-m3-document-library-backend.md` 第 3 节 |
| `documents.program_id` 恒为 NULL；将来若真按项目索引材料，要先想清它与 `task_id` 谁说了算 | M3 设计 | design.md D13 与 Open Questions 3 |
| 护照类材料在 M3 里审不了：只有 `gs` 要点有核验过的官方来源 | M3 设计 | design.md D9 与 Open Questions 5 |
| `HomeView`/`FlowView` 的标签解析已改服务端，但组合列表仍靠镜像守卫兜底 | M2d | 待目录增长到第二类学位/方向时复查 |
