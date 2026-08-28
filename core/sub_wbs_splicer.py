# -*- coding: utf-8 -*-
import json
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _is_move_in_task(name: str) -> bool:
    """判定是否为真正的搬家/移交执行任务 (排除'搬家公司选标'这类采购任务)。"""
    n = str(name)
    if "搬家公司" in n:
        return False
    return any(k in n for k in ["搬家", "搬迁", "正式入驻", "Relocation", "Site Handover", "正式营业"])

def _infer_weave(name: str) -> str:
    """对未显式标注 weave 的 addon 任务, 按关键词推断阶段 (design/procure/construct/validate)。"""
    n = str(name)
    if "设计" in n:
        return "design"
    if "采购定标" in n or "交货" in n or "Lead Time" in n:
        return "procure"
    if any(k in n for k in ["验证", "ISO", "采样", "计数", "检漏", "调试", "完成", "通过"]):
        return "validate"
    return "construct"

# 预编译前置任务正则表达式
PREDECESSOR_SPLIT_REGEX = re.compile(r"^(\d+)(.*)$")

def _find_main_anchor(result_tasks: List[Dict[str, Any]], kind: str) -> Optional[int]:
    """在主体任务中查找锚点 ID (均在搬家阶段之前, 插入 addon 时不会位移)。"""
    if kind == "design":
        # 主体施工图深化/设计深化叶子节点 -> 洁净室/实验室专项设计并行于此
        for t in result_tasks:
            nm = str(t.get("name", ""))
            if "施工图深化" in nm or "施工图设计" in nm or "设计深化" in nm:
                return t["id"]
        return result_tasks[0]["id"] if result_tasks else None
    if kind == "site_takeover":
        for t in result_tasks:
            if "场地移交" in str(t.get("name", "")):
                return t["id"]
        return result_tasks[0]["id"] if result_tasks else None
    if kind == "final_accept":
        # 竣工联合验收/验收合格 叶子节点 (取最后一个匹配)
        aid = None
        for t in result_tasks:
            nm = str(t.get("name", ""))
            if t.get("outline_level", 9) >= 3 and any(
                k in nm for k in ["联合验收通过", "竣工备案", "验收合格意见书", "验收通过"]
            ):
                aid = t["id"]
        return aid
    return None

def splice_sub_modules(main_tasks: List[Dict[str, Any]], addons_str: str, sub_modules_path: str) -> List[Dict[str, Any]]:
    """
    根据选项动态挂载外部 WBS 附加子模块 (洁净室/实验室/数据中心/冷却塔/入苏备案等)。

    编织策略:
      - 模块任务带 weave 字段 (design/procure/construct/validate) -> 阶段编织:
          design 首任务 锚 主体施工图深化 (早期并行); construct 首任务 锚 场地移交 且 设备已交货;
          validate 末节点 强制卡口 竣工验收 + 搬家/移交。避免整体 end-load。
      - 模块无 weave 字段 (如数据中心假负载/冷却塔吊装) -> 线性块插入收尾阶段 (本就是收尾调试, 正确)。
      - 入苏备案模块 -> 插入施工招标阶段 (原有特殊逻辑)。
    """
    if not addons_str:
        return main_tasks

    try:
        with open(sub_modules_path, "r", encoding="utf-8") as f:
            sub_data = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load sub WBS modules at {sub_modules_path}: {e}")
        return main_tasks

    addons = [a.strip() for a in addons_str.split(",") if a.strip()]
    module_terminal_ids: List[int] = []  # 所有注入 addon 的终端(validate/末)节点 ID

    # 拷贝一份避免污染原始引用
    result_tasks = [dict(t) for t in main_tasks]

    for addon in addons:
        if addon not in sub_data.get("sub_modules", {}):
            continue

        module = sub_data["sub_modules"][addon]
        new_tasks = module["tasks"]
        shift_amount = len(new_tasks)

        # ---- 入苏备案: 插入施工招标/RFP 编制之前, 且 RFP/定标 须等备案完成 ----
        if addon == "Suzhou_Permit_Module":
            anchor_kws = ["招标文件", "RFP", "招标", "总包定标", "定标报告", "施工招标"]
            insert_idx = len(result_tasks)
            anchor_name = None
            for i, t in enumerate(result_tasks):
                nm = str(t.get("name", ""))
                if any(kw in nm for kw in anchor_kws):
                    insert_idx = i
                    anchor_name = nm
                    break
            if insert_idx == len(result_tasks):
                # 兜底: 退到 procurement 阶段前
                insert_idx = max(0, len(result_tasks) - 6)
            base_id = result_tasks[insert_idx - 1]["id"] if insert_idx > 0 else (result_tasks[0]["id"] if result_tasks else 0)
            if base_id == 0 and result_tasks:
                base_id = result_tasks[0]["id"]

            spliced_addon_tasks = []
            for idx, nt in enumerate(new_tasks):
                tc = dict(nt)
                tc["id"] = base_id + 1 + idx
                tc["level"] = 3
                tc["outline_level"] = 3
                tc["predecessors"] = str(tc["id"] - 1) if idx > 0 else str(base_id)
                spliced_addon_tasks.append(tc)

            _apply_id_shift_and_insert(result_tasks, spliced_addon_tasks, insert_idx, shift_amount)

            # RFP/招标 节点须等备案完成 (FS 卡口)
            if anchor_name:
                su_last = spliced_addon_tasks[-1]["id"]
                for t in result_tasks:
                    if str(t.get("name", "")) == anchor_name:
                        existing = str(t.get("predecessors", ""))
                        pl = [p.strip() for p in existing.split(",") if p.strip()]
                        if str(su_last) not in pl:
                            pl.append(str(su_last))
                            t["predecessors"] = ",".join(pl)
                            logger.info(f"  [入苏备案卡口] 备案完成 (ID={su_last}) 已写入 '{anchor_name}' 前置卡口。")
                        break
            module_terminal_ids.append(spliced_addon_tasks[-1]["id"])
            continue

        # ---- 其余模块: 判断是否阶段编织 ----
        has_weave = any("weave" in nt for nt in new_tasks)

        # 找插入位置: 搬家/closeout 阶段之前
        insert_idx = len(result_tasks)
        for i, t in enumerate(result_tasks):
            name = str(t.get("name", ""))
            level = t.get("outline_level", t.get("level", 1))
            if level <= 2 and any(kw in name for kw in ["搬家", "搬迁", "Relocation", "验收", "移交", "Closeout"]):
                insert_idx = i
                break
        if insert_idx == len(result_tasks):
            insert_idx = max(0, len(result_tasks) - 2)
        base_id = result_tasks[insert_idx - 1]["id"] if insert_idx > 0 else 0

        # 构建 spliced tasks (新 id, level3, 内部 FS 串接)
        spliced_addon_tasks = []
        for idx, nt in enumerate(new_tasks):
            tc = dict(nt)
            tc["id"] = base_id + 1 + idx
            tc["level"] = 3
            tc["outline_level"] = 3
            if "duration_days" not in tc and "duration" in tc:
                tc["duration_days"] = tc["duration"]
            tc["predecessors"] = str(tc["id"] - 1) if idx > 0 else str(base_id)
            spliced_addon_tasks.append(tc)

        if has_weave:
            # ===== 阶段编织模式 =====
            design_anchor = _find_main_anchor(result_tasks, "design")
            site_takeover = _find_main_anchor(result_tasks, "site_takeover")

            # 各阶段首/末节点 (用新 id)
            phases = {tc["id"]: (tc.get("weave") or _infer_weave(tc["name"])) for tc in spliced_addon_tasks}
            design_ids = [i for i in (tc["id"] for tc in spliced_addon_tasks) if phases[i] == "design"]
            procure_ids = [i for i in (tc["id"] for tc in spliced_addon_tasks) if phases[i] == "procure"]
            construct_ids = [i for i in (tc["id"] for tc in spliced_addon_tasks) if phases[i] == "construct"]
            validate_ids = [i for i in (tc["id"] for tc in spliced_addon_tasks) if phases[i] == "validate"]
            first_design = design_ids[0] if design_ids else None
            last_procure = procure_ids[-1] if procure_ids else None
            first_construct = construct_ids[0] if construct_ids else None
            last_validate = validate_ids[-1] if validate_ids else spliced_addon_tasks[-1]["id"]

            for tc in spliced_addon_tasks:
                iid = tc["id"]
                if iid == first_design and design_anchor is not None:
                    # 专项设计并行于主体施工图深化 (早期, 不 end-load)
                    tc["predecessors"] = str(design_anchor)
                    logger.info(f"  [weave-design] {tc['name']} 锚定主体施工图深化 (ID={design_anchor})")
                elif iid == first_construct and site_takeover is not None:
                    # 洁净/实验室施工: 场地移交 且 设备已交货(lead time 已消耗)
                    preds = [str(site_takeover)]
                    if last_procure is not None:
                        preds.append(str(last_procure))
                    tc["predecessors"] = ",".join(preds)
                    logger.info(f"  [weave-construct] {tc['name']} 锚定场地移交(ID={site_takeover}) + 设备交货(ID={last_procure})")

            module_terminal_ids.append(last_validate)
            logger.info(f"  [weave] 模块 {addon}: design首={first_design} construct首={first_construct} 终端卡口={last_validate}")
        else:
            # ===== 线性块模式 (收尾调试类, 如数据中心/冷却塔) =====
            module_terminal_ids.append(spliced_addon_tasks[-1]["id"])

        _apply_id_shift_and_insert(result_tasks, spliced_addon_tasks, insert_idx, shift_amount)

    # ============ 卡口: 所有注入 addon 终端节点 -> 强制卡口 搬家 + 竣工验收 ============
    final_accept = _find_main_anchor(result_tasks, "final_accept")
    for i, t in enumerate(result_tasks):
        nm = str(t.get("name", ""))
        if t.get("outline_level", t.get("level", 3)) >= 3 and _is_move_in_task(nm):
            existing = str(t.get("predecessors", ""))
            pl = [p.strip() for p in existing.split(",") if p.strip()]
            for gid in module_terminal_ids:
                if str(gid) not in pl:
                    pl.append(str(gid))
                    logger.info(f"  [addon终端卡口] addon 末节点 (ID={gid}) 已强制写入 '{nm}' 前置卡口。")
            t["predecessors"] = ",".join(pl)

    if final_accept is not None:
        for t in result_tasks:
            if t["id"] == final_accept:
                existing = str(t.get("predecessors", ""))
                pl = [p.strip() for p in existing.split(",") if p.strip()]
                for gid in module_terminal_ids:
                    if str(gid) not in pl:
                        pl.append(str(gid))
                        logger.info(f"  [addon竣工卡口] addon 末节点 (ID={gid}) 已强制写入 '竣工验收' 前置卡口。")
                t["predecessors"] = ",".join(pl)
                break

    return result_tasks


def _apply_id_shift_and_insert(result_tasks, spliced_addon_tasks, insert_idx, shift_amount):
    """对 insert_idx 之后的现有任务做 ID 偏移, 重写其 predecessor, 再拼接 spliced 块。"""
    id_map = {}
    for t in result_tasks[insert_idx:]:
        old_id = t["id"]
        new_id = old_id + shift_amount
        id_map[old_id] = new_id
        t["id"] = new_id

    def update_preds(preds_str: str) -> str:
        if not preds_str:
            return ""
        parts = str(preds_str).split(",")
        new_parts = []
        for p in parts:
            p_clean = p.strip()
            if not p_clean:
                continue
            match = PREDECESSOR_SPLIT_REGEX.match(p_clean)
            if match:
                old_p_id = int(match.group(1))
                suffix = match.group(2)
                if old_p_id in id_map:
                    new_parts.append(f"{id_map[old_p_id]}{suffix}")
                else:
                    new_parts.append(p_clean)
            else:
                new_parts.append(p_clean)
        return ",".join(new_parts)

    for t in result_tasks[insert_idx:]:
        t["predecessors"] = update_preds(t.get("predecessors", ""))

    result_tasks[:] = result_tasks[:insert_idx] + spliced_addon_tasks + result_tasks[insert_idx:]
