## ADDED Requirements

### Requirement: Programs are tiered by how far official requirements are met

The result page SHALL place each program whose requirements are collected in exactly one tier, using named
constants that are not attributed to any school:

| Tier | Condition |
| --- | --- |
| 保底 | every compared requirement is met and the average is at least 5 marks above the threshold |
| 稳妥 | every compared requirement is met, but not by enough for 保底 |
| 冲刺 | exactly one compared requirement is unmet, and it is the average by at most 3 marks or the IELTS overall by at most 0.5 |
| 不满足 | any other case |

The page SHALL state that a tier describes the official requirements met, not an admission chance. The tiers
SHALL be named 保底, 稳妥, and 冲刺 everywhere in the interface, matching the stored bands 保, 稳, and 冲. No tier
named `信息不足` SHALL exist.

#### Scenario: A clear margin is a safety

- **WHEN** the applicant's average is 85 on a 100 scale and the program's threshold is 75, with no other
  compared requirement unmet
- **THEN** the program is 保底

#### Scenario: A small shortfall is a reach

- **WHEN** the applicant's average is 73 and the threshold is 75, with every other compared requirement met
- **THEN** the program is 冲刺

#### Scenario: Two shortfalls are not met

- **WHEN** the average is 2 marks short and the IELTS overall is 0.5 short
- **THEN** the program is 不满足

### Requirement: Requirements that cannot be compared are neither met nor unmet

A requirement stored only as text, or missing, SHALL NOT count as met or as unmet. A program with no
comparable requirement SHALL NOT be tiered and SHALL be listed apart under `要求未收录`, with the count of such
programs in the applicant's target field. A tiered program that also has a requirement that cannot be compared
SHALL list it under the tier as `去官网确认`, with the program's official page.

#### Scenario: A program with nothing collected is not tiered

- **WHEN** a program in the applicant's target field has no minimum mark and no numeric English requirement
- **THEN** it appears in no tier and is counted under 要求未收录

#### Scenario: A text-only English requirement is flagged, not judged

- **WHEN** a program has a minimum mark the applicant meets by 10 and an English requirement stored only as text
- **THEN** the program is 保底 on the compared requirement, and its row lists the English requirement as
  去官网确认 with a link to the official page

### Requirement: Institutions without a uniform baseline need human review

When the applicant's institution tier is unknown, or the school is overseas, the academic requirement SHALL be
marked `去官网确认` and not compared. When the school is a mainland school outside 985 and 211, the program's
collected non-211 threshold SHALL be compared if it exists; otherwise the academic requirement SHALL be marked
`去官网确认`. The 985 / 211 threshold SHALL never be applied to a school outside those lists.

#### Scenario: A non-211 school against a tier-dependent threshold

- **WHEN** the applicant's school is a 双非 university and the program's threshold differs for 211 and non-211
  schools but no non-211 threshold is collected
- **THEN** the program is marked 去官网确认 for its academic requirement and is not tiered on it
