# Run lessons (self-iteration log)

Append one block per real schedule run. Newest at top.

## Template

```
### YYYY-MM-DD — <project / city / area>
- Inputs: delivery=, bidding=, start=/target=, cost=
- Result: PASS | FAIL
- Issues:
- Root cause:
- Change made (file):
- Follow-up open:
```

## 2026-09-07 — Dependency Engine v0: sectional SS+lag rule table (Linux, --no_mpp)
- Inputs: city=上海, delivery=DBB, bidding=invite, start=2026-08-28; four runs — 1500㎡/320万 (auto), 20000㎡/8000万 (auto), 20000㎡ `--sectional off`, 20000㎡ `--workfronts 2`
- Result: PASS (tests/test_dependency_engine.py 150/150; tests/test_productivity_pilot.py 58/58; tests/test_v3_basics.py 76/76 with out-of-repo win32/font shim; preflight offline checks PASS; compliance 0 error all runs; no .mpp written)
- Issues:
  1. 1500㎡ auto → workfronts=1, not sectional → 0 rules; finish 2027-05-07, identical to the pre-change baseline task-by-task (all four templates, also 280㎡ Suzhou exempt fold).
  2. 20000㎡ auto → workfronts=8, sectional by area and by workfronts; SEC-01..05 fired: #62 二次机电支管 `59` → `59FF,57SS+3,58SS+3`; #61 墙面封板与天花吊顶龙骨 `59` → `59FF,58SS+4,57SS+4`; #65 天花封石膏板 `63` → `63FF,62SS+4` (lag = ceil(19–24d ÷ 8) clamped to rule range). Finish 2027-12-24 (FS) → 2027-11-16 (sectional). `--workfronts 2` → lags 10–12, finish 2027-11-26 (fewer zones → less overlap, still ≤ FS). Gates stay FF-bound: #61 and #65 finish exactly on their inspection finish.
  3. `compute_cpm_metrics` treated every link as FS in the backward pass; SS predecessors would have shown false negative float under the new rules. Backward pass now honours SS / FF / lag and mirrors the forward same-day milestone convention. Side effect on 1500㎡: 消防设计审查申报 + its milestone move from slack −7 (artifact) to +3 (true parallel-branch float); critical preview count 74 → 72. Remaining negative preview slack (5-day metrics axis vs 7-day site tasks) is pre-existing and out of scope.
  4. Pre-existing, unchanged: `exporters/` imports `pywintypes` / `win32com` / `C:\Windows\Fonts\msyh.ttc` at import, so `main.py --no_mpp` and test 8 need a test-only shim outside the repo on Linux.
- Root cause: template trade links are FS-only through inspection gates; correct for one workfront, over-serial for multi-zone floors.
- Change made (file): `config/dependency_rules.json`, `core/dependency_engine.py`, `core/solver_engine.py` (compute_cpm_metrics + parse_predecessor_token), `main.py` (`--sectional`, `--workfronts`, `_dependencies.json` sidecar), `scripts/preflight.py`, `tests/test_dependency_engine.py`, `SKILL.md`
- Follow-up open: calibrate zone size / lag ranges from real sectional programmes; extend rule table to finishing trades (floor → MEP terminals) once field-validated; per-task calendar in CPM preview axis; Windows+MSP e2e with sectional links (SS/FF/lag already pass through `build_mpp` predecessor strings and the XML sidecar).

## 2026-09-07 — Duration pilot: suspended_ceiling quantity→productivity→duration (Linux, --no_mpp)
- Inputs: city=上海, area=1500, cost=320, delivery=DBB, bidding=invite, start=2026-08-28; run twice, without / with `--productivity_pilot`
- Result: PASS (tests/test_v3_basics.py 76/76; tests/test_productivity_pilot.py 58/58; preflight PASS; compliance 0 error both runs)
- Issues:
  1. Pilot off → log identical to pre-change baseline (finish 2027-05-07, 74 critical nodes). Pilot on → task 61 `墙面封板与天花吊顶龙骨安装` 10d (template, area-calibrated) → 22d (1275㎡ ÷ 60㎡/day = 21.25, ceil), finish 2027-05-18, confidence=low (derived quantity + default crew). Rate 10㎡/worker-day is a pilot placeholder pending field calibration.
  2. Pre-existing: `exporters/` imports `pywintypes` / `win32com` / `C:\Windows\Fonts\msyh.ttc` at module import, so `python main.py --no_mpp` and `import main` (test 8) cannot run on non-Windows despite the SKILL contract. Verified here with a test-only shim outside the repo; not fixed (out of pilot scope).
  3. Pre-existing: final `SUCCESS` log claimed the `.mpp` "landed" even under `--no_mpp` → fixed in main.py (message now states no .mpp was written).
- Root cause: legacy WBS carries no quantity; durations were hard-coded per template then area-scaled.
- Change made (file): `core/productivity.py`, `config/productivity_rates.json`, `main.py` (opt-in flag + sidecar JSON), `scripts/preflight.py`, `tests/test_productivity_pilot.py`, `SKILL.md`
- Follow-up open: calibrate rate/ratio from real takeoffs; guard Windows-only imports in `exporters/`; Windows+MSP e2e with the pilot on (the formula only changes an integer duration, so `build_mpp` path is unchanged).

## 2026-09-07 — Shanghai 20,000㎡ DBB + Substation + Datacenter Physical MPP Run
- Inputs: city="上海", area=20000, cost=8000, delivery=DBB, bidding=invite, target_date="2027-08-30", addons="Datacenter_LoadBank_Module"
- Result: PASS (Full physical .mpp, .pdf, .html, .pptx, .xml all generated)
- Issues: Previous run hung on COM due to modal dialog / orphaned winproj background process. User cleared system dialogs.
- Root cause: Office C2R modal prompt blocked OLE message loop.
- Change made: COM verified with msp_cli.py verify; build_mpp saved 342KB .mpp file; export_pdf generated 263KB A3 PDF table.
- Follow-up open: None (Golden path verified end-to-end on Windows + MS Project).

## 2026-09-07 — v4.1 Full-blood Skill Verification Run
- Inputs: 
  - Case 1: Shanghai 1200㎡, 350万, DB + invite, start=2026-10-15
  - Case 2: Suzhou 280㎡, 80万, DB + invite, start=2026-11-02 (Exempt fold)
  - Case 3: Beijing 3000㎡, 1500万, DBB + public, target=2027-10-30, addon=Datacenter_LoadBank_Module
- Result: PASS (All 76 unit tests PASS, Preflight 100% PASS, 3 E2E cases executed successfully)
- Issues:
  1. `exporters/mpp_renderer.py` imported `responsibility` relatively without checking `core.responsibility`.
  2. `exporters/export_pdf.py` lacked `export_pdf` wrapper function expected by `exporters/__init__.py`.
- Root cause: Refactoring of universal exporter package into `exporters/` left two dangling export/import bindings.
- Change made (file): `exporters/mpp_renderer.py`, `exporters/export_pdf.py`
- Follow-up open: None (All exports .html / .pptx / CPM solved successfully with full compliance).

## 2026-09-04 — v4.1 packaging

- Inputs: n/a (contract upgrade)
- Result: PASS (unit: exempt fold on Suzhou 200㎡/80万 removes permit nodes; property kept)
- Issues closed: SKILL FS-vs-SS conflict; is_exempt dead code; Step4 gate; offline-only permit wording
- Change made: SKILL.md, task_utils.fold_exempt_construction_permit, main.py compliance block, KB/README sync
- Follow-up open: Windows+MSP e2e still required on buyer machine
