## Context

TASKS.md P0 #4. Baseline first, then the fix; tune on 50 questions, report on 30 held-out ones once.

## Decisions

- **D1 Eval labels are predicates, checked against the database.** A question lists the school ids it
  names and optionally a `Program.field` and a name regex; relevant rows are those that also carry
  requirement data and a citable source. The runner refuses to score when a label's `answerable` flag
  disagrees with the database, so a catalogue change cannot silently re-grade the set. Recall@K divides
  by min(K, relevant), because K=4 cannot hold 24 relevant rows. K is read from `evidence.TOP_K`.
- **D2 Aliases are a JSON file keyed by university id, not a table.** 165 universities and 267
  short forms; a table would add a migration and a seed for no query benefit, since matching a question
  against names happens in Python either way (the universities table is read per question, 165 rows).
  CI's eval job checks every key exists.
- **D3 Traditional/simplified folding uses OpenCC's full character table** (4,105 entries, 51 KB,
  Apache-2.0), applied to both sides, instead of a new dependency (opencc) or a hand-picked list.
- **D4 Subject words map to `Program.field`; names only rank.** Each entry's English gloss must be filed
  under its field by `app.collect.fields`, which a unit test checks, so the vocabulary cannot drift from
  the classifier. Words that also mean something else in a requirement question (语言, 材料, 规划, 数据)
  are left out.
- **D5 Requirement data is a gate condition.** A CRICOS-only row (course name, no requirement) answered
  every Melbourne and Macquarie question with 未知 under an official-looking citation. Now those are
  refused as 还没有采到官方录取要求, with the count of names held.
- **D6 Narrowing by a specific subject looks at all rows, collected or not.** When 数据科学 fits only rows
  without requirements, the school answers nothing instead of handing over the computer science row.
- **D7 The no-school refusal's counts are cached for ten minutes** (it aggregates the catalogue); every
  other path reads only the named schools' rows.

## Risks

- Short forms are curated by hand; a wrong one would route a question to the wrong school. The file
  excludes forms that are common words (多大) or name several schools (中大, 南大), and a test fails if
  one folded form names two ids.
- `Program.field` is assigned from English names by keyword rules, so a misfiled program is missed by a
  subject question about its real area.
