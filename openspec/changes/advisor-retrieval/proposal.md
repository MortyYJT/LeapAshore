## Why

The advisor refused questions it could answer and answered ones it should not. Measured on the
pre-change code with a labelled eval set (`api/evals/`, tune split, 34 requirement questions): 18 of 25
answerable questions were refused (false-block 0.72), Recall@4 was 0.05, and every question loaded all
7,496 programs into Python (about 11,100 rows read, 36 statements). Causes: school names matched only
as exact substrings of the stored name (so 帝国理工 missed 帝国理工学院, and 香港大学 missed the stored
香港大學); subjects matched only when a Chinese keyword appeared in the program's (mostly English) name;
a school-only match returned the first rows in table order (AI, molecular medicine for a computing
question); the refusal text listed five Australian schools whatever the catalogue held.

## What Changes

- **School recognition from data**: the catalogue's names (simplified and traditional Chinese folded
  through OpenCC's character table, English, the abbreviation in the English name's parentheses) plus a
  curated short-form file `api/data/advisor/university_aliases.json` keyed by university id. Longest
  non-overlapping match wins. No school is named in code.
- **Subjects select `Program.field`**: `api/data/advisor/subjects.json` maps applicant words to the
  study area `app.collect.fields` assigns; a name pattern ranks rows inside the area, and a specific
  subject (金融, not 商科) keeps only the fitting rows when a school has any.
- **The gate also requires requirement data**: a row that only names a course (the CRICOS extract) is
  not evidence.
- **Filtering in SQL**: one query per question selects at most K rows per named school; two indexes
  (`programs.university_id`, `program_prerequisites.program_id`, add-only migration) keep it to that
  school's rows.
- **Refusals worded from counts**: no school recognised; school without collected requirements;
  school without the subject; no citable source. A comparison that names an uncollected school says so
  in the evidence.
- The portfolio search tool (`search_programs`) uses the same recognition.
- The model-free eval runs in CI against a seeded and imported catalogue.

## Impact

- Code: `api/app/agent/{catalog_match,evidence,graph,state,tools}.py`, `api/app/models/program.py`.
- Schema: one Alembic revision adding two indexes. No table or column changes.
- Data: three files under `api/data/advisor/` (aliases, subjects, OpenCC character map, Apache-2.0).
- CI: a new `advisor-eval` job.
