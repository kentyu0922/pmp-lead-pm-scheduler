# -*- coding: utf-8 -*-
"""
scripts/clean_dist.py - 打包前自动化净化脚本 (Pre-packaging Sanitizer)
===================================================================
在打包发布或提交归档前运行本脚本，自动执行：
1. 递归扫描并删除所有 __pycache__/ 与 *.pyc 字节码缓存；
2. 清理 output_mpp/ 下所有跑批产生的 .mpp, .xml, .html, .pptx, .log 临时文件；
3. 保留 output_mpp/.gitkeep 与 output_mpp/README.md；
4. 清理各类编辑临时文件与无用日志。

运行方式：
  python scripts/clean_dist.py
"""

import os
import shutil
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def clean_project():
    print(f"[clean_dist] 开始净化项目根目录: {BASE_DIR}")
    cleaned_count = 0

    # 1. 清理 __pycache__
    for root, dirs, files in os.walk(BASE_DIR, topdown=False):
        for d in dirs:
            if d == "__pycache__":
                target_dir = os.path.join(root, d)
                try:
                    shutil.rmtree(target_dir)
                    print(f"  [RMDIR] 成功移除缓存: {os.path.relpath(target_dir, BASE_DIR)}")
                    cleaned_count += 1
                except Exception as ex:
                    print(f"  [WARN] 移除失败 {target_dir}: {ex}")

    # 2. 清理 *.pyc, *.pyo, *.log, *.bak
    for ext in ["*.pyc", "*.pyo", "*.log", "*.bak"]:
        for f in glob.glob(os.path.join(BASE_DIR, "**", ext), recursive=True):
            try:
                os.remove(f)
                print(f"  [RMFILE] 成功删除临时文件: {os.path.relpath(f, BASE_DIR)}")
                cleaned_count += 1
            except Exception as ex:
                print(f"  [WARN] 删除失败 {f}: {ex}")

    # 清理根目录测试杂项
    root_test_pptx = os.path.join(BASE_DIR, "test.pptx")
    if os.path.exists(root_test_pptx):
        try:
            os.remove(root_test_pptx)
            print(f"  [RMFILE] 成功删除临时测试文稿: test.pptx")
            cleaned_count += 1
        except Exception:
            pass

    # 3. 清理 output_mpp 下的非说明文件
    output_dir = os.path.join(BASE_DIR, "output_mpp")
    if os.path.exists(output_dir):
        for item in os.listdir(output_dir):
            if item in [".gitkeep", "README.md"]:
                continue
            item_path = os.path.join(output_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                print(f"  [RM-OUT] 移除输出残留: output_mpp/{item}")
                cleaned_count += 1
            except Exception as ex:
                print(f"  [WARN] 清理输出残留失败 {item_path}: {ex}")

    print(f"\n[clean_dist] 净化完成！共处理 {cleaned_count} 处缓存与残留文件。项目已达发布级纯净标准。")

if __name__ == "__main__":
    clean_project()
