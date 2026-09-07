# -*- coding: utf-8 -*-
"""
export_pdf.py - 向后兼容代理 (Backwards Compatibility Proxy)
============================================================
架构重构说明：
PDF 报表与甘特图生成器已归入通用 `exporters/` 组件。
本模块作为根目录向后兼容代理，透传导入 `exporters.export_pdf`。
推荐新代码直接使用：`from exporters import export_pdf`
"""

from exporters.export_pdf import *

if __name__ == "__main__":
    from exporters.export_pdf import main
    main()
