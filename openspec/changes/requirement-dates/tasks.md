## Progress checklist

Branch `claude/requirement-dates`.

- [x] 1.1 Migration: `programs.academic_requirement`, `program_deadlines`
- [x] 1.2 Red/green: importer writes verified deadlines and academic summary; failed ones absent
- [x] 1.3 Red/green: rerun writes nothing (rows, ids, `updated_at`)
- [x] 1.4 Red/green: `has_requirement_data` counts academic-only and deadline-only programs
- [x] 1.5 API serves `academicRequirement` and `deadlines` (programs, portfolio)
- [x] 1.6 Advisor evidence line carries academic requirement and deadlines
- [x] 2.1 Red/green: `deadlineOf` (own date wins, next upcoming, 已截止, 未收录; Beijing today)
- [x] 2.2 Roadmap, portfolio and program page use it; `statesARequirement` follows the rule
- [x] 2.3 Walkthrough covers the roadmap deadline display
- [x] 3.1 README / PRD numbers recomputed
- [ ] 3.2 Deploy: backup, migrate, import, read-only counts, entered dates unchanged
