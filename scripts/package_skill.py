# -*- coding: utf-8 -*-
"""
scripts/package_skill.py - 打包纯净 Skill 发布包 (Clean Distribution Packager)
=============================================================================
功能：
1. 自动调用 clean_project() 预先执行深度净化；
2. 过滤所有 __pycache__、*.pyc、*.log、output_mpp 临时产物；
3. 将工程打包为标准的 ZIP 格式（顶层包裹 pmp-lead-pm-scheduler 根目录）；
4. 同时输出到本地 dist/ 目录与用户桌面 (Desktop)。
"""

import os
import zipfile
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

ROOT_FOLDER_NAME = "pmp-lead-pm-scheduler"

# 排除目录和后缀
EXCLUDE_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".git", ".vscode", ".idea", "dist", "build", "scratch",
    "dev_tools",
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".log", ".tmp", ".bak"}


def should_exclude(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    parts = norm.split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
    _, ext = os.path.splitext(rel_path)
    if ext in EXCLUDE_EXTS:
        return True
    if parts[0] == "output_mpp":
        if len(parts) > 1 and parts[1] not in [".gitkeep", "README.md"]:
            return True
    if parts[0] in {"CHANGELOG-v4.1.md", "README.md", "export_html.py", "test.pptx"}:
        return True
    return False


def build_skill_package(dist_zip_name: str = "pmp-lead-pm-scheduler.zip"):
    print(f"[package_skill] 准备打包工作目录: {BASE_DIR}")
    
    # 1. 确保净化脚本先运行
    try:
        from clean_dist import clean_project
        clean_project()
    except Exception:
        pass

    # 2. 目标输出路径
    dist_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    out_zip_path = os.path.join(dist_dir, dist_zip_name)
    if os.path.exists(out_zip_path):
        os.remove(out_zip_path)

    total_files = 0
    with zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(BASE_DIR):
            # 过滤排除目录以加速
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, BASE_DIR)
                if should_exclude(rel_path):
                    continue
                arc_name = os.path.join(ROOT_FOLDER_NAME, rel_path)
                zf.write(full_path, arc_name)
                total_files += 1

    file_size = os.path.getsize(out_zip_path)
    print(f"\n[package_skill] 成功生成 ZIP: {out_zip_path}")
    print(f"  -> 打包文件总数: {total_files} 个")
    print(f"  -> 纯净压缩体积: {file_size:,} 字节 ({file_size / 1024:.1f} KB)")

    # 3. 尝试同步复制到用户桌面 Desktop
    desktop_dir = os.path.abspath(os.path.join(BASE_DIR, ".."))
    if os.path.exists(desktop_dir) and "Desktop" in desktop_dir:
        desktop_target = os.path.join(desktop_dir, dist_zip_name)
        try:
            shutil.copy2(out_zip_path, desktop_target)
            print(f"  -> 成功同步至桌面: {desktop_target}")
        except Exception as ex:
            print(f"  -> 复制到桌面提示: {ex}")

    return out_zip_path


if __name__ == "__main__":
    build_skill_package()
