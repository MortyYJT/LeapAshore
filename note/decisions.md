# 决策记录

只追加，不改旧条目。每条：日期、决定、理由、影响。属于某个 OpenSpec change 的决定优先写进那个 change，这里只记跨 change 的决定。

## 2026-10-10 先装开发流程 v2，再重新规划产品

- **决定**：顺序为 ① 装流程 v2（`claude/workflow-v2` 分支，从 main 开）→ ② 对整个产品做 brainstorm，用 SDD 重新规划和排期 → 再开发。M4（`stage-2-m4-conversations-and-proposals`）暂停，等 brainstorm 结论出来再决定保留、修改还是废弃。
- **理由**（MortyYJT 原话）：「我们这个产品其实是没有规划好要做什么的，我们现在来做，用 sdd，然后排期啥的开发」。
- **影响**：M4 分支 `dsh/stage-2-m4-conversations` 原样保留，不开 PR。M1–M3 学习材料按交接默认异步派给 dsh，不阻塞。

## 2026-10-10 分工：Codex 实现，dsh 出题

- **决定**：从现在起，实现由 Codex 负责（按 issue、在独立 worktree 里 TDD），dsh 负责出题和阶段复盘，不再做主要实现者。
- **理由**：MortyYJT 选了推荐项，没有另写理由。推荐时给的理由：dsh 对仓库历史最熟，适合写复盘；实现和出题分开，避免「自己考自己」。
- **影响**：分支前缀以后主要是 `codex/` 和 `claude/`；dsh 的产出放在 `note/interview/`。

## 2026-10-10 只装 guard hook，不装 verify hook

- **决定**：安装 `.claude/hooks/guard.sh`（PreToolUse），不装 `verify.sh`（Stop）。推翻了之前「两个 hook 都不装」的做法。
- **理由**：MortyYJT 选了推荐项，没有另写理由。推荐时给的理由：v2 由 Claude 自动推送、开 PR，需要真的拦住远端危险操作；`make verify` 要起数据库、跑截图，挂在每个回合结束时跑太慢。
- **影响**：完成前的检查仍靠手动跑 `make verify` 和 CI。
