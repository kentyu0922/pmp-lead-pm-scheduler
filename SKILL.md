---
name: pmp-lead-pm-scheduler
description: Mainland China office fit-out master schedule. Confirm start or target date, DB or DBB, invite or public bidding, city, area and cost, then run main.py to export mpp, pdf and pptx. Use when the user asks for 排期, 进度计划, 工期推演, Master Programme, or MPP export.
metadata:
  version: "4.2.0"
  last_verified: "2026-09-07"
---

# Lead PM Scheduler

Executable contract for the agent and `main.py`. Marketing stays on the landing page.

Native `.mpp` requires Windows plus desktop Microsoft Project. Otherwise run with `--no_mpp` and deliver `.pdf` plus `.pptx`. Do not claim an `.mpp` was written. Do not generate HTML cockpits.

## When to use

User wants a China fit-out master programme, duration takeoff, permit-aware schedule, or Project file.

## Step 0 — Ask before solving

Confirm all four anchors. If any is missing, ask with options. Never invent dates.

1. Schedule anchor (one required)
   - Forward — `--start_date YYYY-MM-DD`
   - Backward — `--target_date YYYY-MM-DD`
2. Delivery × bidding
   - `--delivery DB` or `DBB`
   - `--bidding invite` or `public`
   - Map
     - DB + invite → `MNC_Standard_Fitout_DB_Invite`
     - DB + public → `MNC_Standard_Fitout_DB_Public`
     - DBB + invite → `MNC_Standard_Fitout_DBB_Invite`
     - DBB + public → `MNC_Standard_Fitout_Office_DBB`
3. `--city` (offline `config/city_permit.json`; unknown city → national default, confidence=low)
4. `--area` (㎡) and `--cost` (万元 RMB, state tax assumption)

Design vs contractor procurement is decided only by `--delivery` template choice. Do not pass `--skip_design_procurement`. That flag is unused and must not delete tasks.

CLI rejects missing date and missing delivery/bidding in non-interactive mode.

## Command

Only entry — `python main.py`.

```bash
python main.py --city 上海 --area 1500 --cost 320 --delivery DBB --bidding invite --start_date 2026-08-28 --project_name "上海1500㎡办公工装" --output case.mpp
```

Backward example — replace `--start_date` with `--target_date 2027-09-14`.

No Project / non-Windows — add `--no_mpp`. Solver still writes `.pdf` and milestone `.pptx`. `.xml` may exist as a Project interchange sidecar; do not present HTML as a deliverable.

Windows-only deps (`pywin32`, `C:\Windows\Fonts\msyh.ttc`) are imported/resolved lazily: `import main` and `--no_mpp` work on Linux/macOS; touching COM (`build_mpp`, `MSProjectSession`, `export_pdf.read_tasks`) raises `MSProjectUnavailableError`. PDF falls back to a system CJK font, then to reportlab's built-in `STSong-Light`; override with `PMP_PDF_FONT=/path/to/font.ttf`. Test: `python tests/test_no_win32_import.py`.

Do not run `dev_tools/`. Do not call COM except through `exporters/mpp_renderer.py` → `build_mpp`.

## Solve rules (do not reimplement)

- City rules and holidays only from `config/` JSON. No live web lookups for statutes.
- Exempt permit → fold government construction-permit tasks; keep property review and fire path.
- Predecessor-only links. FS / SS / FF with optional lag allowed. Do not write Successor fields.
- Dual calendars — design/gov on client workdays; site and purge on construction 7×8 with Spring Festival to Lantern Festival off.
- Integer workdays. Dual IAQ sequence required.
- Compliance errors block delivery (`COMPLIANCE_BLOCKED`). Infeasible backward schedule fails loudly.

City or holiday edits go in JSON only, then bump `metadata.last_verified`.

## Duration engine — quantity → productivity → duration (opt-in)

Default off. Template hard-coded durations remain the path for every task. Activity types in the rate library: `suspended_ceiling`, `partition_framing`, `flooring`, `painting`. Opt-in bridge:

- `--productivity_pilot` — tagged WBS tasks are re-timed as `quantity ÷ (rate × crew) × factors`, ceil to integer workdays, floored at `min_duration_days`. Everything else keeps its template duration.
- `--pilot_activities <a,b,…|all>` — which types to bridge onto the legacy template (keyword match: `天花吊顶龙骨` / `隔墙轻钢龙骨` / `地板/地砖/地毯` / `乳胶漆`). Default `suspended_ceiling` only, so the flag alone behaves exactly as the v4.2 pilot.
- `--quantities type=㎡,…` — measured takeoffs per type (`--ceiling_area` is the alias for `suspended_ceiling`). Without one, quantity = `--area × ratio` from the bridge and confidence is downgraded (`derived_from_area`). Quantity derivation beyond that ratio is out of scope here.
- `--rate_level low|typical|high` — pick a rate table column. `low` = pessimistic productivity (longest duration), `typical` = default, `high` = optimistic. A task may also pin `rate_level`. Only these configured columns exist; there is no way to pass a number.
- Rates (`rates_per_worker_day`), crew defaults, factor tables and the keyword bridges live only in `config/productivity_rates.json`. The library is validated on load (all three levels present, non-decreasing, bridge factors exist) and fails loudly. Tasks in any task list may also carry `activity_type` + `quantity` (+ `crew_size`, `factors`, `rate_level`) directly.
- Never invent a rate or a duration. Task-level `productivity_rate` / `rate_per_worker_day` keys are ignored with a warning; the model may choose an activity type, quantity, crew, factor key and rate level, and nothing else. Rate calibration is a JSON edit plus version bump.
- Explainable fields are attached to the task (`productivity`, `duration_method`) and written to `output_mpp/<output>_productivity.json`: quantity, unit, productivity_rate, rate_level, rate_table, crew_size, factors, calculated_duration, final_duration, duration_by_rate_level, template_duration, confidence + reasons.
- Unknown activity type, missing quantity, bad factor key or unknown rate level → warning, template duration kept. Never raises inside the pipeline.

Tests: `python tests/test_productivity_pilot.py` (ceiling fixture 1200㎡ / 10㎡·worker-day / crew 6 / complex 1.2 → 24d; templates unchanged with the pilot off; gate with it on) and `python tests/test_productivity_engine.py` (partition 900㎡/15/6 → 10d, flooring 1350㎡/25/5 → 11d, painting 2700㎡/35/6 → 13d; rate-level ranges; config-only guard; four-trade pipeline through the verification gate).

## Quantity Engine v0 — benchmark quantities without a BOQ

Default off. Derives `ceiling_area, flooring_area, partition_length, partition_area, drywall_partition_area, glass_partition_area, paint_area` from gross `--area` × building grade, deterministically. Formulas live in `core/quantity_engine.py`; every ratio, height, share and sanity band lives only in `config/quantity_benchmarks.json` (grades A/B/C with documented assumptions; layouts `open_plan 0.8 / standard 1.0 / cellular 1.3` on partition density). No LLM guessing, no live lookups.

- `--derive_quantities` — run the engine and write `output_mpp/<output>_quantities.json` (value, unit, substituted formula, per-gross-m² ratio, sanity band, assumptions, warnings). Changes no duration.
- `--grade A|B|C` (aliases `甲级`, `Grade A`, …; default A) and `--layout open_plan|standard|cellular` (default standard) feed the engine.
- Hook into the productivity path: when `--productivity_pilot` is on and no measured `--ceiling_area` / `--quantities suspended_ceiling=…` is given, the ceiling quantity comes from the engine's `ceiling_area` via the rate entry's `quantity_key` (precedence: measured → engine → legacy `area × 0.85` bridge). Other pilot trades (`partition_framing`, `flooring`, `painting`) declare no `quantity_key` yet and keep their bridge ratios. Any task list task with `activity_type` but no `quantity` is filled the same way through `apply_productivity_durations(..., derived_quantities=…)`. Derived quantities keep `quantity_source = derived_from_area`, so confidence is downgraded exactly as before.
- Grade A + standard reproduces the PR #3 pilot number (1500㎡ → 1275㎡ → 22d). Output outside a sanity band is a warning, never silent.
- Fixture: 1500㎡ Grade A → ceiling 1275㎡, flooring 1380㎡, partition 450 m / 1575㎡, drywall 1023.8㎡, glass 551.2㎡, paint 2569.1㎡. All values are uncalibrated benchmarks; a measured BOQ always wins.

Tests: `python tests/test_quantity_engine.py`.
## V5 architecture — iron rule, defaults, engine flags

Iron rule (applies to the agent and to every engine):

- **The LLM only classifies.** It may pick the template (delivery × bidding), name an `activity_type`, choose factor *keys* (`complexity: complex`, `access: high_ceiling`), judge whether an optimizer suggestion is acceptable to the PM. It never emits a duration, a date, a rate, a crew size or a float value.
- **Duration comes only from DB + formula.** Either the hard-coded template number (`templates/wbs_templates.json` → `core/calibration.py`) or `config/productivity_rates.json` × the formula in `core/productivity.py`. A number typed into a prompt or produced by the model is not a duration source. Unknown type / missing quantity → template duration kept, warning logged.
- **Dates come only from the solver.** `core/solver_engine.py` on `config/holidays.json`. Float and critical path in the optimizer are computed from that solve, never guessed.
- **Legacy templates stay the default.** Every engine below is opt-in. With no flag, `main.py` output is byte-identical to v4.1.

| Flag | Default | What turns on |
|------|---------|---------------|
| `--productivity_pilot` | off | tagged trades' duration via quantity ÷ (rate × crew) × factors (section above) |
| `--pilot_activities <list\|all>` | `suspended_ceiling` | which bridged activity types the pilot tags (`suspended_ceiling,partition_framing,flooring,painting` or `all`) |
| `--ceiling_area <㎡>` / `--quantities type=㎡,…` | Quantity Engine `quantity_key` (ceiling) or `--area × bridge ratio` | measured takeoff per activity type; raises confidence one level |
| `--rate_level low\|typical\|high` | `typical` | which configured rate-table level applies; values come only from `config/productivity_rates.json` |
| `--derive_quantities` | off | Quantity Engine v0 (section above); writes `output_mpp/<output>_quantities.json`, changes no duration |
| `--grade A\|B\|C` / `--layout open_plan\|standard\|cellular` | `A` / `standard` | benchmark inputs for the Quantity Engine; values come only from `config/quantity_benchmarks.json` |
| `--optimizer` | off | read-only Schedule Optimizer v0 (below); writes `output_mpp/<output>_optimizer.json` |

Not built yet (other cards): `quantity_key` wiring for partition / flooring / paint activity types, dependency engine, resource/crash optimizer. Do not describe them as available.

### Schedule Optimizer v0 (`--optimizer`, `core/optimizer.py`)

What it does, from the solve output only:

- **Critical path / float summary.** Calendar-aware backward pass that inverts the solver's FS / SS / FF + lag rules on each task's own calendar (construction 7-day / standard 5-day / 24h) → total float in working days; the *driving chain* (predecessor that actually set each start, from Kick-off to the latest finish); float distribution, near-critical list (float 1–5), per-phase critical counts. Deterministic: same input → identical JSON.
- **ONE fast-track rule.** For consecutive plain-FS pairs on the driving chain: propose `succ: predSS+(dur_pred − overlap)` with `overlap = floor(min(dur_pred, dur_succ) × 0.5)`, capped at 5 working days. Every suggestion cites both activities (id, name, duration, dates, float, calendar), the current and proposed relationship token, an upper-bound saving, and `why` / `risk` text. Durations are copied from the baseline, never changed or invented.
- **Excluded from overlap, by keyword, with the reason recorded:** government / statutory windows (审查 审批 备案 许可 报监 …), inspection & acceptance (验收 检测 复测 盲测 …), the dual-IAQ chain (空气 散味 通风 家具 …), tender / award / contract windows (招标 投标 清标 定标 中标 合同 …), handover / relocation, milestones, links that are already SS/FF or lagged, co-driven successors, pairs too short for a ≥1-day overlap.
- **Verification, not application.** Each suggestion is re-solved on a deep copy (`solve_schedule`) and reports `baseline_finish → new_finish`, calendar-day saving, whether the driving chain changed, and compliance errors after the change. The baseline task list, `.pdf`, `.pptx` and any `.mpp` are unchanged; every suggestion carries `applied_to_baseline: false`.

Honest limits of v0:

- It suggests; it does not apply. If the PM accepts a suggestion, edit the successor's predecessor token in the task list / template (or in MS Project) and re-run. When you do, say exactly what changed: task id, `before → after` token, and why. Never apply an optimizer change silently.
- One heuristic, one ratio (0.5) and one cap (5d), not calibrated to trade data. Only FS→SS overlap; no crashing, no resource levelling, no evaluation of several suggestions together (savings do not add).
- A driving task can show float > 0 at a calendar boundary (7-day milestone ending Sunday before a 5-day task starting Monday). The optimizer flags this (`calendar_boundary_float`) instead of forcing it to 0; MS Project shows the same slack.
- The legacy preview `compute_cpm_metrics` (5-day axis, FS-only) still feeds the existing PDF/PPTX `critical` marks and is reported as `legacy_preview_critical_count`; the two counts can disagree. When an `.mpp` is produced, MS Project remains the authority for dates and float.

Standalone (no MS Project): `python core/solver_engine.py tasks.json` then `python core/optimizer.py tasks.solved.json --out opt.json`.

Tests: `python tests/test_optimizer_v0.py` (fixture network + all four templates: summary fields, driving chain, no negative float, ≥1 suggestion citing real activities / floats / tokens, baseline not mutated, re-solve saving ≥ 0 with compliance 0 error, determinism).

## Verification gate

Before calling the job done:

1. No task with empty Start/Finish after solve
2. `compliance.run_compliance_checks` has zero `error`
3. IAQ chain present — first IAQ → treatment if any → furniture → purge → second IAQ
4. If exempt — no 正式取得施工许可证 / government permit-application tasks; property review remains
5. If not exempt — permit milestone present
6. Gov/permit tasks not on construction 7-day; trades not forced onto 5-day only
7. Critical path non-empty in preview metrics
8. `.mpp` only via `build_mpp`, or `--no_mpp` stated to the user
9. If `--optimizer` was used — report suggestions as *not applied*; quote saving only from the re-solve (`verified.new_finish`), and if the PM accepts one, state the task id and `before → after` predecessor token before re-running

On failure — fix and regenerate. Do not deliver a known-bad file.

Gate 4 is automated, not manual-only: `python tests/test_exempt_fold_gate4.py` (Suzhou 280㎡ / 80万 / DB + invite / start 2026-11-02 — permit phase, application and 正式取得施工许可证 milestone folded; property review, 图审 and fire path retained; Site Takeover rewired to 图审 + 物业送审; compliance 0 error; all four templates; non-exempt control keeps the permit milestone). `scripts/preflight.py` runs the same fold as a smoke gate.

## Failure modes

| Situation | Behavior |
|-----------|----------|
| No MS Project / COM | `--no_mpp`; deliver pdf/pptx; say mpp skipped |
| Unknown city | National default + confidence=low |
| Cost unit unclear | Ask 万元 RMB, tax, furniture/ELV in scope |
| Backward infeasible | Fail loudly |
| Compliance errors | Block (`COMPLIANCE_BLOCKED`) |
| Illegal delivery/bidding | SystemExit with hint |

## After a real run

Append `docs_and_sops/process/run_lessons.md`. Next edit — read that file and `docs_and_sops/process/skill_routing_verification.md` first. Prefer tests under `tests/` for calendar, IAQ, and exempt-fold regressions.

Detail SOPs live under `docs_and_sops/`. Read a file only when the current project needs that specialty.
