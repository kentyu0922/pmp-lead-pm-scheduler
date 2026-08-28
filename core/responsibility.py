# -*- coding: utf-8 -*-
"""责任识别引擎（纯 Python，可单测）。

依据任务所属阶段（Phase 1-9，由任务名关键词识别）自动判定：
  - 执行单位（responsible_unit）  ：谁来做这件事
  - 责任人（responsible_person）  ：具体对接/负责的人或角色
  - 责任标识（responsibility_flag）：★ 直接负责 / ○ 配合审核 / ▲ 关键里程碑 / ◎ 阶段统筹

任务级可 override：任务字典里出现 responsible_unit / responsible_person /
responsibility_flag 任意字段即优先采用，未提供字段回落到自动识别。
"""
from __future__ import annotations

# 阶段规则：按顺序匹配，命中第一条即停。
# pattern 为出现在任务名中的关键词；unit/person 为该阶段默认执行单位与责任人。
_PHASE_RULES = [
    # Phase 1 启动与规划
    (("Phase 1", "项目启动", "Kick Off", "Kickoff", "PEP", "执行计划", "物业装修申请",
      "CI导则", "机电图获取", "概念", "规划", "前置", "启动"), "业主方 PMO", "项目经理"),
    # Phase 2 设计深化
    (("Phase 2", "设计", "图审", "效果图", "平面", "SD", "施工图", "专项设计",
      "功能分区", "布局规划", "材料选型", "图审合格证", "图纸送审", "安全协议",
      "翻图", "LDI", "复核", "盖章", "扩初", "专项编制", "深化", "出图", "规范"), "设计院", "设计负责人"),
    # Phase 3 招采
    (("Phase 3", "招标", "招采", "RFP", "BOQ", "短名单", "回标", "清标", "定标", "合同",
      "R1", "R2", "BAFO", "LOI", "ROA", "谈判", "备标"), "业主方招采组", "招采经理"),
    # Phase 4 报建/许可
    (("Phase 4", "施工许可", "许可证", "申报"), "报建专员", "政府建管窗口"),
    # Phase 5 长周期采购
    (("Phase 5", "采购", "家具", "设备", "FFU", "HEPA", "供应商", "交货", "Lead Time",
      "选标"), "业主方采购组", "对应品类供应商"),
    # Phase 6 实体施工（覆盖机电/装饰/实验室/屋面/冷却塔等专业表述）
    (("Phase 6", "施工", "Stage", "隐蔽", "地坪", "彩钢板", "围护", "龙骨", "拆除",
      "清运", "桥架", "管道", "排风", "调试", "联调", "Commissioning", "保洁",
      "更衣", "净化", "面板", "灯具", "五金", "缺陷整改", "场地移交", "动工",
      "机电", "预埋", "1st Fix", "2nd Fix", "Fix", "敷设", "保温", "饰面", "涂料",
      "隔断", "造型", "废气", "排毒", "风管", "吊装", "特殊气体", "高纯", "防爆",
      "管路", "铺设", "打压", "防静电", "PVC", "地板", "理化板", "实验台", "承重",
      "勘测", "工字钢", "减震", "基座", "焊接", "吊车", "冷却塔", "对接", "进场",
      "夜间"), "施工总包", "总包项目经理"),
    # Phase 7 第三方验证
    (("Phase 7", "ISO", "验证", "采样", "粒子", "沉降菌", "空气质量", "盲测",
      "复测", "报告"), "第三方验证机构", "验证工程师"),
    # Phase 8 竣工验收
    (("Phase 8", "竣工", "验收", "备案", "联合审批", "消防", "安监", "环保"), "业主/政府验收组", "验收负责人"),
    # Phase 9 搬迁入驻
    (("Phase 9", "搬迁", "搬家", "入驻", "Handover", "移交", "培训", "交付",
      "运营"), "搬迁组/行政", "搬迁负责人"),
]

# 采购阶段内，按品类细化责任人（在命中 Phase 5 后二次匹配）
_PURCHASE_PERSON = [
    (("家具",), "家具供应商"),
    (("实验室设备", "特种设备"), "实验室设备供应商"),
    (("FFU", "HEPA"), "FFU/HEPA 供应商"),
    (("搬家", "搬迁"), "搬家公司"),
]

# 责任标识判定
_FLAG_MILESTONE = "▲ 关键里程碑"   # 里程碑节点
_FLAG_PHASE = "◎ 阶段统筹"          # 阶段/汇总行
_FLAG_DIRECT = "★ 直接负责"         # 叶子任务直接执行
_FLAG_SUPPORT = "○ 配合/审核"       # 配合、审核、确认类

# 配合/审核类关键词
_SUPPORT_KW = ("配合", "审核", "确认", "送审", "审阅", "审批", "评审", "签字",
               "备案", "获取", "取得", "通过", "分析", "澄清", "谈判")


def _match_phase(name: str):
    """返回 (unit, person) 或 (None, None)。"""
    for kws, unit, person in _PHASE_RULES:
        for kw in kws:
            if kw.lower() in name.lower():
                return unit, person
    return None, None


def _refine_purchase_person(name: str, default_person: str) -> str:
    for kws, person in _PURCHASE_PERSON:
        for kw in kws:
            if kw.lower() in name.lower():
                return person
    return default_person


def _resolve_flag(name: str, is_milestone: bool, outline_level: int) -> str:
    if is_milestone:
        return _FLAG_MILESTONE
    if outline_level <= 2:
        return _FLAG_PHASE
    # 叶子任务：含配合/审核关键词则降为配合，否则直接负责
    for kw in _SUPPORT_KW:
        if kw in name:
            return _FLAG_SUPPORT
    return _FLAG_DIRECT


def resolve_responsibility(task: dict) -> dict:
    """对单个任务字典解析责任三元组，支持任务级 override。

    返回新 dict：{responsible_unit, responsible_person, responsibility_flag}
    （不修改入参）。
    """
    name = str(task.get("name", ""))
    is_milestone = bool(task.get("milestone", False))
    outline_level = int(task.get("outline_level", 3) or 3)

    unit, person = _match_phase(name)
    if unit is None:
        # 兜底：未识别到阶段时，按层级给合理默认，避免落到“待定”
        # 阶段/汇总行（level<=2）→ 项目统筹；其余叶子默认归施工总包
        if outline_level <= 2:
            unit = "业主方 PMO"
            person = "项目经理"
        else:
            unit = "施工总包"
            person = "总包项目经理"

    # 采购阶段按品类细化责任人
    if unit == "业主方采购组":
        person = _refine_purchase_person(name, person)

    # 任务级 override（只覆盖提供了的字段）
    ov_unit = task.get("responsible_unit")
    ov_person = task.get("responsible_person")
    ov_flag = task.get("responsibility_flag")
    if ov_unit:
        unit = ov_unit
    if ov_person:
        person = ov_person
    flag = ov_flag if ov_flag else _resolve_flag(name, is_milestone, outline_level)

    return {
        "responsible_unit": unit,
        "responsible_person": person,
        "responsibility_flag": flag,
    }


def annotate_tasks(tasks: list) -> list:
    """就地补充 responsible_* 字段到每个任务（返回同一 list，便于链式调用）。"""
    for t in tasks:
        t.update(resolve_responsibility(t))
    return tasks


# 自定义字段映射（供渲染器/报表复用，保证命名一致）
FIELD_MAP = {
    "responsible_unit": "Text1",    # 执行单位
    "responsible_person": "Text2",  # 责任人
    "responsibility_flag": "Text3", # 责任标识
}
FIELD_TITLES = {
    "Text1": "执行单位",
    "Text2": "责任人",
    "Text3": "责任标识",
}


if __name__ == "__main__":
    demo = [
        {"name": "Phase 2 设计深化阶段", "outline_level": 2, "milestone": False, "duration": 0},
        {"name": "[M] 图审合格证获取 / 施工图全套确认", "outline_level": 3, "milestone": True, "duration": 0},
        {"name": "施工图深化与智能化专业", "outline_level": 3, "duration": 10},
        {"name": "Phase 3 施工总包邀请招标", "outline_level": 2, "duration": 0},
        {"name": "RFP 正式发出 + 现场踏勘 + Q&A澄清", "outline_level": 3, "duration": 5},
        {"name": "Phase 5 长周期设备与家具采购", "outline_level": 2, "duration": 0},
        {"name": "家具生产交货 Lead Time", "outline_level": 3, "duration": 60},
        {"name": "FFU/HEPA交货 Lead Time", "outline_level": 3, "duration": 45},
        {"name": "Phase 6 实体施工阶段", "outline_level": 2, "duration": 0},
        {"name": "彩钢板围护结构安装(墙板及顶板)", "outline_level": 4, "duration": 8},
        {"name": "Phase 8 竣工验收审批", "outline_level": 2, "duration": 0},
        {"name": "[M] 竣工备案/联合验收通过", "outline_level": 3, "milestone": True, "duration": 0},
    ]
    for t in demo:
        r = resolve_responsibility(t)
        print(f"{t['name'][:30]:32} | {r['responsible_unit']:10} | {r['responsible_person']:12} | {r['responsibility_flag']}")
