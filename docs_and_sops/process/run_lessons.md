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
  6. After merging main (PR #4 lazy win32 + PR #5 Gate4 suite) into this branch: shim no longer needed; `--pilot_activities all --no_mpp` runs natively on Linux with the same 4 formula nodes / finish 2027-06-02; tests/test_productivity_engine.py 95/95, tests/test_productivity_pilot.py 59/59, tests/test_exempt_fold_gate4.py 90/90, tests/test_no_win32_import.py 34/34, tests/test_v3_basics.py 76/76, preflight PASS (incl. Gate4 step).
- Root cause: PR #3 hard-wired the engine to a single scalar rate; low/typical/high tables and multi-type bridging were needed before more trades could use the same formula path.
- Change made (file): `config/productivity_rates.json` (v0.2.0), `core/productivity.py`, `main.py` (`--pilot_activities`, `--quantities`, `--rate_level`), `tests/test_productivity_engine.py`, `tests/test_productivity_pilot.py` (scope assertions only), `SKILL.md`
- Follow-up open: calibrate the four rate tables and area ratios from real takeoffs; quantity derivation (card 3); SS/lag between the framing → boarding → paint chain (card 4); Windows+MSP e2e with `--pilot_activities all` (formula only changes integer durations, `build_mpp` path untouched).
## 2026-09-07 — Gate4 exempt fold into the automated suite (Linux, no COM)
- Inputs: fixture = Suzhou 280㎡, 80万, DB + invite, start=2026-11-02 (run_lessons Case 2, previously manual QA only); non-exempt control = Suzhou 1000㎡/250万 same template
- Result: PASS (tests/test_exempt_fold_gate4.py 90/90; tests/test_productivity_pilot.py 58/58 unchanged; preflight Gate4 step OK — before the lazy-win32 hardening below, only the pre-existing `pywintypes` import failed on Linux; after merging it, preflight passes fully and tests/test_v3_basics.py 76/76 + tests/test_no_win32_import.py 34/34 also pass on the merged tree)
- Issues: none in fold semantics. Locked as-is: exactly 3 nodes fold per template (施工许可证办理 phase summary, 政府施工许可证申报, [M] 正式取得施工许可证); 物业 / 图审 / 消防 node counts unchanged; Site Takeover predecessors rewired to 图审合格证 + 物业送审 (chained expansion keeps parent suffix, drops removed edge's lag, dedups); no dangling ids; idempotent; `is_exempt=False` returns the same list. Thresholds are strict `<` (300㎡/80万 and 280㎡/100万 are not exempt).
- Root cause: Gate4 lived only in SKILL.md checklist + a hand-run case; nothing in `tests/` or preflight asserted fold behavior, so a regression would ship silently.
- Change made (file): `tests/test_exempt_fold_gate4.py` (new), `scripts/preflight.py` (step 3.5 fold smoke gate), `SKILL.md` (Gate 4 test pointer)
- Follow-up open: no CI runner exists in the repo; the suite is `python tests/*.py` + `python scripts/preflight.py`. The pywintypes blocker is cleared by the hardening entry below, so a Linux CI workflow is now unblocked.
## 2026-09-07 — Hardening: lazy/guarded Windows-only deps (Linux, --no_mpp)
- Inputs: city=上海, area=1500, cost=320, delivery=DBB, bidding=invite, start=2026-08-28; run with `--no_mpp`, with `--no_mpp --productivity_pilot`, and once without `--no_mpp` to exercise the COM failure path
- Result: PASS (tests/test_v3_basics.py 76/76 — previously crashed at test 8 `import main` on Linux; tests/test_productivity_pilot.py 58/58; new tests/test_no_win32_import.py 34/34; preflight PASS)
- Issues:
  1. Pre-existing (logged in the pilot entry below): `exporters/mpp_renderer.py` imported `pywintypes`, `exporters/export_pdf.py` imported `pythoncom`/`win32com` and registered `C:\Windows\Fonts\msyh.ttc`, `core/msp_session.py` imported `win32com`/`pythoncom` — all at module import, so `python main.py --no_mpp` and `import main` died with `ModuleNotFoundError: pywintypes` on non-Windows despite the SKILL contract.
  2. `requirements.txt` pinned `pywin32` unconditionally (no Linux/mac wheel → `pip install -r` fails) and omitted `reportlab`, which the PDF path requires.
- Root cause: exporters were written on the Windows+MSP golden path; COM/font side effects lived at import time instead of at call time.
- Change made (file): `core/msp_session.py` (guarded import, `WIN32_AVAILABLE`, `MSProjectUnavailableError`, `require_win32()`; `com_available()` returns False), `exporters/mpp_renderer.py` (lazy `_com_time` → `pywintypes.Time`; `build_mpp` calls `require_win32()` before any side effect), `exporters/export_pdf.py` (COM imports inside `read_tasks`; `_ensure_fonts()` resolves msyh.ttc → system CJK TTF → reportlab CID `STSong-Light`, `PMP_PDF_FONT` override), `main.py` (COM failure logged at error level with `--no_mpp` hint; honest SUCCESS text unchanged), `requirements.txt` (`pywin32; sys_platform == "win32"`, `reportlab`), `tests/test_no_win32_import.py`, `SKILL.md`
- Duration / productivity / template logic untouched: pilot off → finish 2027-05-07, 74 critical; pilot on → task 61 22d, finish 2027-05-18 (identical to the pilot entry below).
- Follow-up open: Windows+MSP golden-path re-run to confirm `_com_time`/`require_win32` are transparent when pywin32 is present (they are pure pass-throughs, not exercised here); `exporters/export_pdf.DEFAULT_MPP` still points at `exporters/output_mpp/` (pre-existing, CLI-only default, not touched).

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
