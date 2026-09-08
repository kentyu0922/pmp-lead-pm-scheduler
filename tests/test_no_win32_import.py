# -*- coding: utf-8 -*-
"""
test_no_win32_import.py — 非 Windows（无 pywin32）环境下的 import / --no_mpp 契约
运行: python tests/test_no_win32_import.py   （任何平台；不需要 MS Project）

SKILL.md 契约：非 Windows 用 `--no_mpp`，仍交付 .pdf/.pptx，且绝不宣称已写出 .mpp。
本测试通过 sys.modules 屏蔽 win32com / pythoncom / pywintypes（在 Windows 上同样模拟"无 pywin32"），证明：
  (a) `import main` / exporters / core.msp_session / core.msp_automation / tools.msp_cli 在无 win32 时可 import
  (b) PDF 字体不在 import 阶段解析；无 C:\\Windows\\Fonts\\msyh.ttc 时仍能导出 PDF（系统中文字体或内建 CID 兜底）
  (c) 只有真正触碰 COM 路径（MSProjectSession / build_mpp / export_pdf.read_tasks）才抛 MSProjectUnavailableError，
      且 build_mpp 失败前不留下任何 .mpp/.xml 副作用
  (d) 子进程端到端：`main.py --no_mpp` 退出码 0，产出 .pdf + .pptx，无 .mpp，日志如实声明未生成 .mpp；
      不带 --no_mpp 时 COM 路径明确报错，同样不产出 .mpp、不宣称成功落地
"""
import os
import sys
import glob
import subprocess
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

WIN32_MODULES = ("win32com", "win32com.client", "pythoncom", "pywintypes", "win32api", "win32con")

# 先于任何项目模块 import：把 Windows-only 模块置为 None，后续 import 一律 ImportError
for _m in WIN32_MODULES:
    sys.modules[_m] = None  # type: ignore

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_imports_without_win32():
    print("== 1. 无 pywin32 时项目模块可 import ==")
    try:
        import win32com.client  # noqa: F401
        check("win32com 已被屏蔽（测试前提）", False, "win32com 仍可 import，屏蔽失效")
    except ImportError:
        check("win32com 已被屏蔽（测试前提）", True)

    import core.msp_session as S
    check("core.msp_session import 不抛错", True)
    check("WIN32_AVAILABLE == False", S.WIN32_AVAILABLE is False)
    check("com_available() 返回 False 而非抛错", S.com_available() is False)

    import core._common as CM
    check("core._common.MSProjectSession 仍可解析(非 None)", CM.MSProjectSession is not None)

    import exporters  # noqa: F401
    from exporters import build_mpp, export_pdf, generate_pptx_milestones  # noqa: F401
    check("exporters 包 + build_mpp/export_pdf/generate_pptx_milestones import 成功", True)

    import core.mpp_renderer  # noqa: F401  (向后兼容代理)
    import core.msp_automation  # noqa: F401
    import tools.msp_cli  # noqa: F401
    check("core.mpp_renderer / core.msp_automation / tools.msp_cli import 成功", True)

    import main  # noqa: F401
    check("import main 成功（test_v3_basics 第 8 节的前提）", hasattr(main, "main"))


def test_pdf_font_lazy():
    print("\n== 2. PDF 字体惰性解析（无 msyh.ttc 亦可导出）==")
    EP = sys.modules["exporters.export_pdf"]  # 包属性被同名函数遮蔽，取模块本体
    check("import 阶段未注册字体(_FONTS_READY False)", EP._FONTS_READY is False)
    check("保留 Windows 首选字体常量", EP.FONT.lower().endswith("msyh.ttc"))

    tasks = [
        {"id": 1, "name": "Phase 1 设计阶段", "outline_level": 2, "duration": 0},
        {"id": 2, "name": "墙面封板与天花吊顶龙骨安装", "outline_level": 3, "duration": 5,
         "start": "2026-09-01", "finish": "2026-09-07", "predecessors": ""},
        {"id": 3, "name": "[M] 竣工验收", "outline_level": 3, "duration": 0, "milestone": True,
         "start": "2026-09-08", "finish": "2026-09-08", "predecessors": "2"},
    ]
    with tempfile.TemporaryDirectory() as td:
        p1 = EP.export_pdf(tasks, os.path.join(td, "t.pdf"), format="table", title="字体回退测试")
        check("table PDF 生成(>1KB)", os.path.exists(p1) and os.path.getsize(p1) > 1000)
        p2 = EP.export_pdf(tasks, os.path.join(td, "g.pdf"), format="gantt", title="字体回退测试")
        check("gantt PDF 生成(>1KB)", os.path.exists(p2) and os.path.getsize(p2) > 1000)
        check("字体来源已记录", bool(EP.FONT_SOURCE), str(EP.FONT_SOURCE))
        print(f"        字体来源: {EP.FONT_SOURCE}")

        # 强制走"找不到任何中文 TTF"分支 → reportlab 内建 CID 字体兜底
        saved = list(EP._FONT_CANDIDATES)
        env_saved = os.environ.pop("PMP_PDF_FONT", None)
        try:
            EP._FONT_CANDIDATES.clear()
            EP._FONTS_READY = False
            p3 = EP.export_pdf(tasks, os.path.join(td, "cid.pdf"), format="table", title="CID 兜底")
            check("无任何 TTF 时用内建 CID 字体兜底成功", os.path.exists(p3) and os.path.getsize(p3) > 1000
                  and "STSong-Light" in str(EP.FONT_SOURCE), str(EP.FONT_SOURCE))
        finally:
            EP._FONT_CANDIDATES.extend(saved)
            EP._FONTS_READY = False
            if env_saved is not None:
                os.environ["PMP_PDF_FONT"] = env_saved


def test_com_paths_fail_loudly():
    print("\n== 3. COM 路径仅在被调用时明确失败 ==")
    import core.msp_session as S
    from exporters import build_mpp
    EP = sys.modules["exporters.export_pdf"]

    try:
        S.MSProjectSession()
        check("MSProjectSession() 抛 MSProjectUnavailableError", False, "未抛错")
    except S.MSProjectUnavailableError as e:
        check("MSProjectSession() 抛 MSProjectUnavailableError", True)
        check("错误信息指向 Windows / --no_mpp", "Windows" in str(e) and "--no_mpp" in str(e), str(e))
        check("MSProjectUnavailableError 是 RuntimeError 子类(旧 except 仍兼容)", isinstance(e, RuntimeError))

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "sub", "x.mpp")
        tasks = [{"id": 1, "name": "任务", "outline_level": 3, "duration": 3, "predecessors": ""}]
        try:
            build_mpp("t", None, tasks, [], out)
            check("build_mpp 抛 MSProjectUnavailableError", False, "未抛错")
        except S.MSProjectUnavailableError:
            check("build_mpp 抛 MSProjectUnavailableError", True)
        check("build_mpp 失败前无副作用(无目录/.mpp/.xml)",
              not os.path.exists(os.path.dirname(out)) and not glob.glob(os.path.join(td, "**", "*"), recursive=True))
        check("build_mpp 失败前未就地改写 tasks(无 responsible_* 注入)", "responsible_unit" not in tasks[0])

        try:
            EP.read_tasks(os.path.join(td, "nonexistent.mpp"))
            check("export_pdf.read_tasks 抛 MSProjectUnavailableError", False, "未抛错")
        except S.MSProjectUnavailableError:
            check("export_pdf.read_tasks 抛 MSProjectUnavailableError", True)


def _run_main(extra_args, output_name):
    """子进程运行 main.py，同样屏蔽 win32 模块；返回 (returncode, log)。"""
    block = "import sys; " + "; ".join(f"sys.modules[{m!r}] = None" for m in WIN32_MODULES)
    argv = ["main.py", "--city", "上海", "--area", "1500", "--cost", "320", "--delivery", "DBB",
            "--bidding", "invite", "--start_date", "2026-08-28", "--project_name", "no_win32_e2e",
            "--output", output_name] + list(extra_args)
    code = f"{block}; sys.argv = {argv!r}; import main; main.main()"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-c", code], cwd=BASE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _outputs(stem):
    d = os.path.join(BASE, "output_mpp")
    return {os.path.basename(p) for p in glob.glob(os.path.join(d, stem + "*"))}


def _cleanup(stem):
    for p in glob.glob(os.path.join(BASE, "output_mpp", stem + "*")):
        try:
            os.remove(p)
        except OSError:
            pass


def test_e2e_no_mpp_subprocess():
    print("\n== 4. 端到端: main.py --no_mpp（子进程，无 win32）==")
    stem = "_test_no_win32_nompp"
    _cleanup(stem)
    try:
        rc, log = _run_main(["--no_mpp"], stem + ".mpp")
        outs = _outputs(stem)
        check("退出码 0", rc == 0, f"rc={rc}\n{log[-1500:]}")
        check("生成 .pdf", f"{stem}.pdf" in outs, str(outs))
        check("生成 _Milestones.pptx", f"{stem}_Milestones.pptx" in outs, str(outs))
        check("未生成 .mpp / .xml", not any(n.endswith((".mpp", ".xml")) for n in outs), str(outs))
        check("日志如实声明未生成 .mpp", "未生成 .mpp" in log)
        check("日志不宣称物理文件落地", "物理文件已通过 100% 审计落地" not in log)
        check("日志无 pywintypes/win32 ImportError 栈", "No module named 'pywintypes'" not in log
              and "Traceback" not in log, log[-800:])
    finally:
        _cleanup(stem)


def test_e2e_com_path_invoked_subprocess():
    print("\n== 5. 端到端: main.py 不带 --no_mpp（COM 路径被调用 → 明确报错，不伪造 .mpp）==")
    stem = "_test_no_win32_com"
    _cleanup(stem)
    try:
        rc, log = _run_main([], stem + ".mpp")
        outs = _outputs(stem)
        check("流程按 SKILL 失败模式继续交付 pdf/pptx(退出码 0)", rc == 0, f"rc={rc}\n{log[-1500:]}")
        check("日志明确记录 COM 失败原因(MS Project COM 不可用)", "MS Project COM 不可用" in log, log[-1200:])
        check("日志提示改用 --no_mpp", "--no_mpp" in log)
        check("未生成 .mpp / .xml", not any(n.endswith((".mpp", ".xml")) for n in outs), str(outs))
        check("仍生成 .pdf + .pptx", f"{stem}.pdf" in outs and f"{stem}_Milestones.pptx" in outs, str(outs))
        check("日志不宣称物理文件落地", "物理文件已通过 100% 审计落地" not in log and "未生成 .mpp" in log)
    finally:
        _cleanup(stem)


if __name__ == "__main__":
    test_imports_without_win32()
    test_pdf_font_lazy()
    test_com_paths_fail_loudly()
    test_e2e_no_mpp_subprocess()
    test_e2e_com_path_invoked_subprocess()
    print(f"\n==== 结果: PASS={PASS}  FAIL={FAIL} ====")
    sys.exit(1 if FAIL else 0)
