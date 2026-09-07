# -*- coding: utf-8 -*-
"""
export_pptx.py - 向后兼容代理 (Backwards Compatibility Proxy)
=============================================================
架构重构说明：
高管级里程碑 PPTX 生成器已归入通用 `exporters/` 组件。
本模块作为根目录向后兼容代理，透传导入 `exporters.export_pptx`。
推荐新代码直接使用：`from exporters import generate_pptx_milestones`
"""

from exporters.export_pptx import *

if __name__ == "__main__":
    from exporters.export_pptx import main
    main()
