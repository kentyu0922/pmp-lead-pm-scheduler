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

## 2026-09-07 — V5-A: productivity engine generalized (partition_framing / flooring / painting + suspended_ceiling; Linux, --no_mpp)
- Inputs: city=上海, area=1500, cost=320, delivery=DBB, bidding=invite, start=2026-08-28; four runs: pilot off / `--productivity_pilot` (default = ceiling only) / `--pilot_activities all` / `--pilot_activities all --rate_level low --quantities partition_framing=1200,flooring=1000 --ceiling_area 900`
- Result: PASS (tests/test_productivity_pilot.py 59/59; tests/test_productivity_engine.py 95/95; preflight unchanged — only the pre-existing `pywintypes` import item; compliance 0 error in all four runs)
- Issues:
  1. Pilot off → finish 2027-05-07, 74 critical nodes (identical to the PR #3 baseline). Ceiling-only → task 61 22d, finish 2027-05-18 (identical to PR #3, so the rate-table refactor did not move the pilot number).
  2. `all` → 4 formula nodes, every other node duration identical to the legacy run: #57 隔墙轻钢龙骨骨架搭设 partition_framing 900㎡ ÷ (15×6) = 10d (template 8d); #61 suspended_ceiling 1275㎡ → 22d (10d); #65 天花封石膏板与墙顶乳胶漆饰面 painting 2700㎡ ÷ (35×6) × scope=with_ceiling_board 1.5 = 19.29 → 20d (9d); #66 架空防静电地板/地砖/地毯铺设 flooring 1350㎡ ÷ (25×5) = 10.8 → 11d (6d). Finish 2027-06-02. Confidence low everywhere (derived quantity + default crew).
  3. `--rate_level low` + measured quantities → 20 / 19 / 27 / 14d, finish 2027-06-18; each `duration_by_rate_level` range is echoed in the sidecar JSON and the explain log.
  4. Formula durations run 1.3–2.4× longer than the area-calibrated template values at 1500㎡. The template values were tuned as composite crew allowances; the rate tables are industry rules of thumb pending field calibration. Not tuned here — that is a JSON edit once takeoffs exist.
  5. Linux run still needs a test-only shim for `pywintypes` / `win32com` / `msyh.ttc` (card 1). No `.mpp` produced or claimed.
- Root cause: PR #3 hard-wired the engine to a single scalar rate; low/typical/high tables and multi-type bridging were needed before more trades could use the same formula path.
- Change made (file): `config/productivity_rates.json` (v0.2.0), `core/productivity.py`, `main.py` (`--pilot_activities`, `--quantities`, `--rate_level`), `tests/test_productivity_engine.py`, `tests/test_productivity_pilot.py` (scope assertions only), `SKILL.md`
- Follow-up open: calibrate the four rate tables and area ratios from real takeoffs; quantity derivation (card 3); SS/lag between the framing → boarding → paint chain (card 4); Windows+MSP e2e with `--pilot_activities all` (formula only changes integer durations, `build_mpp` path untouched).

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
