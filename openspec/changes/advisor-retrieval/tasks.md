## Progress checklist

Branch `claude/advisor-retrieval`.

- [x] 1.1 Eval set: 80 AI-labelled questions (50 tune / 30 held-out), runner, baseline committed before any code change
- [x] 1.2 Baseline with the model for intent accuracy (deepseek-chat), recorded with token use
- [x] 2.1 School recognition: catalogue names, OpenCC folding, curated short forms, longest match
- [x] 2.2 Subject vocabulary to `Program.field`, gloss consistency test
- [x] 2.3 Gate: requirement data, SQL filtering with per-school round robin, indexes migration
- [x] 2.4 Refusal text from counts; the graph shows the gate's text
- [x] 2.5 `search_programs` uses the same recognition
- [x] 3.1 Tests for each listed question; model-free eval in CI with thresholds
- [x] 3.2 Held-out split run once on the final code (Recall@4 0.889, false-pass 0, false-block 0; see TASKS.md)
