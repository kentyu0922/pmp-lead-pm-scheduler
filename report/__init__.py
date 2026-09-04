"""A3 executive schedule report generator for the AI Lead PM Scheduler.

Modules:
    cpm_engine      Deterministic CPM (Kahn topological sort, forward/backward pass).
    sample_project  1,000 sqm commercial office fit-out baseline WBS + risk register.
    risk_analytics  Float distribution, seeded Monte Carlo, criticality index, risk scoring.
    fonts           Typeface resolution (Noto Sans TC + Inter, with system fallbacks).
    theme           Warm-white palette, A3 grid and typographic scale.
    a3_report       ReportLab canvas renderer (Summary / Gantt / Critical Path / Risk).
"""
