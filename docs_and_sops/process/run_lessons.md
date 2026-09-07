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

## 2026-09-07 — Quantity Engine v0 (V5-B): benchmark quantities without a BOQ (Linux, --no_mpp)
- Inputs: city=上海, area=1500, cost=320, delivery=DBB, bidding=invite, start=2026-08-28; five runs: default / `--derive_quantities` / `--productivity_pilot` (grade A default) / `--productivity_pilot --grade C --layout cellular` / `--productivity_pilot --grade 甲级 --ceiling_area 900`
- Result: PASS (tests/test_quantity_engine.py 102/102; tests/test_productivity_pilot.py 58/58; tests/test_v3_basics.py 76/76; preflight PASS; compliance 0 error in every run)
- Issues:
  1. Default run log identical to origin/main (finish 2027-05-07, 74 critical nodes). `--derive_quantities` alone → same finish, writes `<output>_quantities.json` (ceiling 1275 / flooring 1380 / partition 450 m, 1575㎡ / drywall 1023.8 / glass 551.2 / paint 2569.1㎡), changes no duration.
  2. Pilot + engine grade A → task 61 quantity 1275㎡ via `quantity_key=ceiling_area` → 22d, finish 2027-05-18 — identical to the PR #3 pilot (Grade A `net_ceiling_ratio` 0.85 == legacy bridge ratio). Grade C cellular → 1200㎡ → 20d, finish 2027-05-17. `--ceiling_area 900` overrides the engine (measured, 15d, finish 2027-05-12).
  3. `--grade Z` → SystemExit with the allowed grades/aliases (no silent default).
  4. Pre-existing `pywintypes` / font import problem in `exporters/` unchanged; `main.py` runs verified with the same out-of-repo shim as the PR #3 record. No `.mpp` produced or claimed.
- Root cause: legacy WBS carries no quantities and the pilot's only source was a single hard-coded `area × 0.85`; ceiling/partition/flooring/paint benchmarks did not exist.
- Change made (file): `core/quantity_engine.py` (new), `config/quantity_benchmarks.json` (new, grades A/B/C + layouts + assumptions + sanity bands), `core/productivity.py` (hook: measured → engine `quantity_key` → legacy ratio), `config/productivity_rates.json` (`quantity_key`), `main.py` (`--derive_quantities`, `--grade`, `--layout`, `_quantities.json` sidecar), `scripts/preflight.py`, `tests/test_quantity_engine.py`, `SKILL.md`
- Follow-up open: calibrate every benchmark from real takeoffs (all values are documented rules of thumb, confidence=low); card 2 to add partition / flooring / paint activity types with `quantity_key`s pointing at the new quantities; Windows+MSP e2e with the engine on.

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
