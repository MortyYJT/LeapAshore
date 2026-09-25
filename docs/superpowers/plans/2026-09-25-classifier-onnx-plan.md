# Intent Classifier and ONNX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, measured intent classifier with an ONNX inference option that can assist, but never override, the guarded Agent workflow.

**Architecture:** Define an OfferPilot-specific multi-label or single-label taxonomy from real product flows. Create deduplicated, provenance-tracked, human-reviewed train/validation/test splits. Train and calibrate offline; deploy inference as a separate optional service. The LangGraph router uses it only when the dataset and held-out gates pass, otherwise sends ambiguous cases to the existing LLM or deterministic path.

**Tech Stack:** PyTorch, Transformers, scikit-learn, tokenizers, ONNX, ONNX Runtime, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-mewhelp-full-stack-rebuild-design.md`

## Global Constraints

- No real applicant messages are exported to a third-party model or public dataset.
- Keep source provenance, consent basis, redaction status, labeler, and taxonomy version for each retained sample.
- Split by normalized text and conversation/source group before training; exact and near-duplicate leakage across splits is zero.
- Classifier confidence is advisory; high-impact or out-of-distribution requests use existing guarded routes.
- Training dependencies stay in an optional ML dependency group and do not inflate the API runtime image.

## Review Focus

- Label conflicts and multi-intent sentences follow a written, tested taxonomy policy.
- Train/test leakage check catches exact and normalized duplicates.
- Empty, very long, multilingual, typo-heavy, and out-of-distribution text does not crash or gain false high confidence.
- Torch and ONNX predictions agree within a documented tolerance on the frozen test set.
- Missing model artifact or inference outage falls back cleanly without changing hard constraints.

---

### Task 1: Define taxonomy and annotation contract

**Files:**
- Create: `api/app/intent_taxonomy.py`
- Create: `api/evals/data/intent_annotation_guide.md`
- Create: `api/tests/test_intent_taxonomy.py`

**Interfaces:** Taxonomy maps a stable `intent_id` to description, positive examples, exclusions, risk tier, and required workflow route. Sample record stores provenance and taxonomy version.

- [ ] Derive classes from actual endpoints and current advisor actions; document boundaries for planning, official knowledge, profile update, action proposal, complaint/safety, and other.
- [ ] Add test fixtures for ambiguous and overlapping requests; assert intended single/multi-label behavior.
- [ ] Write annotation guide with tie-break rules, unknown/uncertain label, and review procedure.
- [ ] Require two-person review for disagreements in the frozen evaluation set.
- [ ] Review class inventory with product owner before producing training labels.

### Task 2: Build de-identified corpus and leakage gates

**Files:**
- Create: `api/evals/intent_corpus.py`
- Create: `api/evals/intent_splits.py`
- Create: `api/evals/check_intent_leakage.py`
- Create: `api/tests/test_intent_splits.py`
- Create: `api/evals/data/intent_samples/` (approved, non-sensitive samples only)

**Interfaces:** `build_splits(samples, seed, ratios) -> DatasetSplits`; `check_leakage(splits) -> LeakageReport`. The report contains counts and hashes, not raw messages.

- [ ] Add tests that identical normalized text, same conversation group, or same synthetic template family cannot cross splits.
- [ ] Add tests for insufficient class counts and missing provenance; fail training before data split.
- [ ] Implement deterministic split seed and record corpus/taxonomy hashes.
- [ ] Add a de-identification scanner and manual review manifest before a sample may be committed.
- [ ] Run corpus checks; if real labels are insufficient, stop at offline benchmark and do not fabricate production readiness.

### Task 3: Train, evaluate, calibrate, and export

**Files:**
- Create: `api/evals/train_intent.py`
- Create: `api/evals/evaluate_intent.py`
- Create: `api/evals/export_intent_onnx.py`
- Create: `api/evals/scan_intent_thresholds.py`
- Create: `api/tests/test_intent_onnx.py`
- Modify: `api/pyproject.toml`, `.gitignore`

**Interfaces:** Training outputs model artifact metadata with corpus hash, taxonomy version, seed, model version, and metrics; ONNX interface is `classify(text) -> {labels, scores, model_version}`.

- [ ] Add CPU-only smoke tests with a tiny checked-in synthetic dataset; assert deterministic preprocessing and schema, not model quality.
- [ ] Put torch/transformers/scikit-learn/onnx/onnxruntime/tokenizers into an optional `ml` extra or dependency group.
- [ ] Train only from approved split manifest; write artifacts under ignored `data/intent/models/`.
- [ ] Report per-class precision/recall/F1, macro and micro F1, confusion matrix, calibration, threshold sweep, and support counts.
- [ ] Export ONNX and compare output labels/scores against the source model within documented tolerance.
- [ ] Review held-out metrics against explicit class-specific gates before approving online routing.

### Task 4: Add optional inference service and router fallback

**Files:**
- Create: `api/app/classifier_client.py`
- Create: `api/evals/serve_intent.py`
- Modify: `api/app/graph/routing.py`, `api/app/settings.py`, `compose.yaml`
- Create: `api/tests/test_classifier_client.py`

**Interfaces:** `classify_intent(text, timeout) -> IntentPrediction | None`; `None` represents missing, low-confidence, or unavailable classifier and triggers existing routing logic.

- [ ] Add client tests for valid result, low confidence, OOD result, timeout, bad schema, and model-version mismatch.
- [ ] Implement inference server with no storage of request bodies and bounded request size/rate.
- [ ] Add feature flag default-off and require a matching approved model/corpus/taxonomy version tuple.
- [ ] Add graph tests that classifier output cannot route around source evidence checks or user confirmation.
- [ ] Enable only after held-out quality and shadow-route criteria pass; otherwise leave model offline.
