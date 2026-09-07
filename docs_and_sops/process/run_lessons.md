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

## 2026-09-07 — Schedule Optimizer v0 + SKILL V5 section (Linux, --no_mpp)
- Inputs: (1) city=上海, area=1500, cost=320, DBB + invite, start=2026-08-28, with / without `--optimizer`; (2) city=北京, area=3000, cost=1500, DB + public, target=2027-10-30, `--optimizer --productivity_pilot --ceiling_area 2400`
- Result: PASS (tests/test_optimizer_v0.py 351/351; tests/test_productivity_pilot.py 58/58; tests/test_v3_basics.py 76/76 with the out-of-repo COM stub; preflight PASS; default run log identical to origin/main)
- Issues:
  1. Legacy `compute_cpm_metrics` flags 74/89 tasks critical with slack down to −48 on the Shanghai DBB case (5-day axis, FS-only). Not usable as a float basis for suggestions → optimizer computes its own calendar-aware backward pass (62 float-0 tasks, driving chain 59, no negative float). Legacy preview left untouched for PDF/PPTX compatibility and reported alongside.
  2. Solver FS rule treats any predecessor with start == finish (0-day *and* 1-day tasks) as "successor starts same day". The backward pass must mirror that or every 1-day task on the chain leaks 1 day of negative float. Mirrored; fixture test locks it.
  3. A 7-day-calendar milestone ending Sunday before a 5-day task starting Monday carries 1 working day of real float although it drives the finish. Reported as `calendar_boundary_float`, not forced to 0.
  4. Shanghai DBB: three FS→SS suggestions (65→66, 66→67, 67→68; 3d overlap each) each re-solve to 2027-05-07 → 2027-04-30, compliance 0 error. Beijing backward case: same rule saves only 1 calendar day because a parallel path binds — the report says so instead of claiming 3.
- Root cause: no read-only analysis layer existed between solve and export; float preview was approximate.
- Change made (file): `core/optimizer.py` (new), `core/solver_engine.py` (`build_calendar_bitmaps` refactor, behaviour unchanged), `main.py` (`--optimizer` + sidecar), `scripts/preflight.py`, `tests/test_optimizer_v0.py`, `SKILL.md` (V5 section, gate 9, version 4.2.0), `README.md`
- Follow-up open: calibrate overlap ratio / cap per trade pair; consider replacing the legacy preview with the calendar-aware pass in reports (separate card); Windows + MS Project run with `--optimizer` to compare float against MSP Total Slack; `exporters/` Windows-only imports still block `import main` on Linux (pre-existing, out of scope).

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
