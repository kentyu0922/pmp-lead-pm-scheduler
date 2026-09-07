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
