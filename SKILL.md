---
name: pmp-lead-pm-scheduler
description: Mainland China office fit-out master schedule. Confirm start or target date, DB or DBB, invite or public bidding, city, area and cost, then run main.py to export mpp, pdf and pptx. Use when the user asks for 排期, 进度计划, 工期推演, Master Programme, or MPP export.
metadata:
  version: "4.1.0"
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

## Duration pilot — quantity → productivity → duration (one activity type)

Default off. Template hard-coded durations remain the path for every task. Opt-in bridge:

- `--productivity_pilot` — the `suspended_ceiling` WBS task (name matches `天花吊顶龙骨`) is re-timed as `quantity ÷ (rate × crew) × factors`, ceil to integer workdays, floored at `min_duration_days`. Everything else keeps its template duration.
- `--ceiling_area <㎡>` — measured ceiling takeoff. Without it, quantity = `--area × 0.85` and confidence is downgraded (`derived_from_area`).
- Rates, crew defaults, factor tables and the template keyword bridge live only in `config/productivity_rates.json`. Tasks in any task list may also carry `activity_type` + `quantity` (+ `crew_size`, `factors`) directly.
- Explainable fields are attached to the task (`productivity`, `duration_method`) and written to `output_mpp/<output>_productivity.json`: quantity, unit, productivity_rate, crew_size, factors, calculated_duration, final_duration, template_duration, confidence + reasons.
- Unknown activity type, missing quantity or bad factor key → warning, template duration kept. Never raises inside the pipeline.

Tests: `python tests/test_productivity_pilot.py` (formula fixture 1200㎡ / 10㎡·worker-day / crew 6 / complex 1.2 → 24d; all four templates unchanged with the pilot off; verification gate with it on).

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
