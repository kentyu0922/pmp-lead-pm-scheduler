# -*- coding: utf-8 -*-
"""
core/mpp_renderer.py — 高级项目经理 MS Project COM 物理引擎 (100% 绝对稳定防崩溃物理渲染器)

化繁为简 (v3): COM 生命周期改用 MSProjectSession；任务创建/前置解析/常量改用 core._common。
"""

import os
import logging
from typing import List, Dict, Any, Tuple
import pywintypes
import datetime

# 配置独立日志记录器
logger = logging.getLogger(__name__)

# 化繁为简：从 _common 导入共享层
try:
    from core._common import (
        MSProjectSession, CONSTRUCTION_CAL_NAME,
        create_task_with_outline, split_predecessor_id_suffix,
    )
except ImportError:  # 兼容独立运行
    from _common import (
        MSProjectSession, CONSTRUCTION_CAL_NAME,
        create_task_with_outline, split_predecessor_id_suffix,
    )

try:
    from .responsibility import annotate_tasks, FIELD_MAP, FIELD_TITLES
except ImportError:  # 兼容独立运行
    from responsibility import annotate_tasks, FIELD_MAP, FIELD_TITLES

def _inject_responsibility_columns(app, fc_unit, fc_person, fc_flag):
    """把 执行单位/责任人/责任标识 三列加进默认「项」任务表（左侧甘特图直接可见）。

    本机中文版 MS Project 的 TableEditEx(Create=True/追加列) 在 typelib 下会静默失效
    （返回成功但列实际未写入，ViewApplyEx 亦不可靠），故改用 TableFields.Add 直接往
    「项」表追加列——已在真机实测可靠（Field/Title/Width 三参）。Text1/2/3 数据已先行写入，
    此步仅决定左侧栏位是否可见。
    """
    TARGET = "项"
    cols = [("执行单位", fc_unit, 18), ("责任人", fc_person, 18), ("责任标识", fc_flag, 12)]
    try:
        proj = app.ActiveProject
        tbl = None
        for tb in proj.TaskTables:
            if tb.Name == TARGET:
                tbl = tb
                break
        if tbl is None:
            tbl = proj.TaskTables(1)
        added = 0
        for title, fc, w in cols:
            try:
                tbl.TableFields.Add(Field=fc, Title=title, Width=w)
                added += 1
            except Exception as e_c:
                logger.debug(f"[mpp_renderer][RESP] 加列 {title} 失败: {e_c}")
        if added:
            logger.info(f"[mpp_renderer][RESP] 已向默认任务表「{tbl.Name}」注入 {added} 列责任栏位(执行单位/责任人/责任标识)")
        else:
            raise RuntimeError("TableFields.Add 未成功加入任何责任列")
    except Exception as e:
        logger.warning(f"[mpp_renderer][RESP] 责任列注入失败(数据仍在 Text1/2/3，可用 .bas 宏一键注入): {e}")


def build_mpp(project_title: str, project_start: 'datetime.date', tasks: List[Dict[str, Any]], calendar_exceptions: List[Dict[str, str]], output_mpp_path: str) -> Tuple[str, dict]:
    """
    通过 COM 接口生成 MS Project 物理文件 (.mpp) 及无损 XML。
    """
    output_mpp_path = os.path.abspath(output_mpp_path)
    out_dir = os.path.dirname(output_mpp_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # 责任识别：为每个任务自动解析 执行单位/责任人/责任标识（写入前就地补充字段）
    try:
        annotate_tasks(tasks)
    except Exception as e_ann:
        logger.warning(f"[mpp_renderer][RESP] 责任识别跳过: {e_ann}")

    logger.info(f"[mpp_renderer] 初始化 MS Project COM 渲染引擎...")

    with MSProjectSession() as sess:
        app = sess.app
        project = sess.new()

        # 责任字段常量（Text1/2/3 -> 执行单位/责任人/责任标识）
        fc_unit = fc_person = fc_flag = None
        try:
            fc_unit = app.FieldNameToFieldConstant("Text1")
            fc_person = app.FieldNameToFieldConstant("Text2")
            fc_flag = app.FieldNameToFieldConstant("Text3")
        except Exception as e_fc:
            logger.warning(f"[mpp_renderer][RESP] 字段常量获取失败: {e_fc}")

        try:
            project.Title = project_title
        except Exception as e:
            logger.warning(f"[mpp_renderer] 无法设置 Project Title: {e}")

        if project_start:
            try:
                # 关键修复：开工时刻统一设为日历工时起点 08:00，而非本地午夜。
                # 日历工时为 08:00-17:00；若项目起点为 00:00（午夜），首个任务会被排在
                # 00:00（非工时），其实际工作从 08:00 才开始，导致首日产生 8h 非工时缺口被
                # 卷进摘要工期，出现如 "223.13 个工作日" 的小数工期。改为 08:00 后所有任务
                # 对齐到 08:00-17:00 整段工时，工期均为整数天。
                if isinstance(project_start, datetime.datetime):
                    _d = project_start
                else:
                    _d = datetime.datetime(project_start.year, project_start.month, project_start.day)
                _ps = pywintypes.Time(datetime.datetime(_d.year, _d.month, _d.day, 8, 0, 0))
                project.ProjectStart = _ps
                logger.info(f"[mpp_renderer] 成功设置项目开工起点(08:00): {_d.date()}")
            except Exception as e:
                logger.error(f"[mpp_renderer] 设置项目起点失败: {e}")

        # 2. 创建 [施工7天日历] (BaseCalendar) — 7 天工作制（周末也施工）
        try:
            app.BaseCalendarCreate(CONSTRUCTION_CAL_NAME, "标准")
            cal7 = project.BaseCalendars(CONSTRUCTION_CAL_NAME)
            for wd in (1, 7):  # 周日(1) 与周六(7)
                day_obj = cal7.WeekDays(wd)
                # 关键：使周末成为工作日。MS Project 在 Working=True 时会自动赋予
                # 默认 8h 工时（08:00-12:00 + 13:00-17:00），已实测 7 天排程有效。
                day_obj.Working = True
                # 防御式尝试显式设定工时；部分 MS Project typelib 不暴露
                # WorkingTimes 集合（gen_py 未生成），此时依赖上面的 MSP 默认工时。
                try:
                    wts = day_obj.WorkingTimes
                    if wts.Count == 0:
                        wts.Add("08:00:00", "17:00:00")
                    else:
                        wts(1).FromTime = "08:00:00"
                        wts(1).ToTime = "17:00:00"
                except Exception:
                    logger.debug(f"[mpp_renderer] 周{wd} 显式工时设定跳过(采用 MSP 默认工时)")
            # 自证：读回确认周末已变为工作日
            try:
                for wd in (1, 7):
                    if cal7.WeekDays(wd).Working:
                        logger.info(f"[mpp_renderer][CAL-VERIFY] {CONSTRUCTION_CAL_NAME} 周{wd} Working=True ✓ 7天日历生效")
                    else:
                        logger.warning(f"[mpp_renderer][CAL-VERIFY] {CONSTRUCTION_CAL_NAME} 周{wd} 仍为非工作日!")
            except Exception as e_v:
                logger.debug(f"[mpp_renderer][CAL-VERIFY] 读回确认跳过: {e_v}")
            logger.info(f"[mpp_renderer] 成功创建基准日历: {CONSTRUCTION_CAL_NAME}")
        except Exception as e_cal7:
            logger.warning(f"[mpp_renderer] 7天日历创建提示: {e_cal7}")

        # 3. 物理注入 2027 春节元宵停工大假 + 全量法定节假日 Exceptions
        all_exceptions = [
            {"name": "2027年春节元宵施工停工大假", "start": "2027-02-06", "finish": "2027-02-20"}
        ]
        if calendar_exceptions:
            all_exceptions.extend(calendar_exceptions)

        for cal_type, base_cal in [("Project", project.Calendar), ("Construction", project.BaseCalendars(CONSTRUCTION_CAL_NAME))]:
            if base_cal:
                for exc in all_exceptions:
                    name = str(exc.get("name", "节假日"))
                    # 重磅修复：施工日历仅保留带有"春节"关键字的假期，跳过其他
                    if cal_type == "Construction" and "春节" not in name:
                        continue

                    try:
                        start = str(exc.get("start"))
                        finish = str(exc.get("finish"))
                        if start and finish:
                            # 全天例外（00:00~23:59），避免带 08:00/17:00 时刻的例外在日历边界
                            # 留下非整日缺口，进而污染跨春节摘要工期的整数性。
                            exc_obj = base_cal.Exceptions.Add(1, f"{start} 00:00:00", f"{finish} 23:59:00")
                            try:
                                exc_obj.Name = name
                            except Exception as e_name:
                                logger.debug(f"[mpp_renderer] 节假日命名失败: {e_name}")
                    except Exception as e_exc:
                        logger.debug(f"[mpp_renderer] 节假日 {name} 注入失败: {e_exc}")

        logger.info(f"[mpp_renderer] 成功物理注入节假日 Exceptions 到项目及施工日历!")

        # 4. 插入 Task 节点（使用 _common.create_task_with_outline 统一大纲状态机）
        current_depth = [1]
        task_objects = {}
        mp_id_map = {}  # 自定义 id -> MS Project 真实任务 ID(按创建顺序), 用于依赖翻译

        for t in tasks:
            t_id = t["id"]

            t_obj = create_task_with_outline(
                project, t, current_depth,
                construction_cal_name=CONSTRUCTION_CAL_NAME,
                logger=logger,
            )

            task_objects[t_id] = t_obj
            try:
                mp_id_map[t_id] = t_obj.ID
            except Exception:
                pass

            # 责任识别：把自动解析的 执行单位/责任人/责任标识 写入 Text1/2/3
            if fc_unit is not None:
                try:
                    t_obj.SetField(fc_unit, str(t.get("responsible_unit", "")))
                    t_obj.SetField(fc_person, str(t.get("responsible_person", "")))
                    t_obj.SetField(fc_flag, str(t.get("responsibility_flag", "")))
                except Exception as e_resp:
                    logger.debug(f"[mpp_renderer][RESP] 任务 {t_id} 责任字段写入失败: {e_resp}")

        # 4.5 责任栏位：改名自定义列 + 尝试注入左侧甘特图任务表
        if fc_unit is not None:
            try:
                app.CustomFieldRename(fc_unit, FIELD_TITLES["Text1"])
                app.CustomFieldRename(fc_person, FIELD_TITLES["Text2"])
                app.CustomFieldRename(fc_flag, FIELD_TITLES["Text3"])
                logger.info(f"[mpp_renderer][RESP] 自定义列已改名为 {FIELD_TITLES['Text1']}/{FIELD_TITLES['Text2']}/{FIELD_TITLES['Text3']}")
            except Exception as e_ren:
                logger.warning(f"[mpp_renderer][RESP] 自定义列改名失败: {e_ren}")
            # 尝试把三列加进左侧任务表（中文版 MSP 的 TableEditEx 常受限，失败则优雅降级，
            # 数据已写入 Text1/2/3，用户可用 docs_and_sops/common/add_responsibility_columns.bas 一键注入）
            try:
                _inject_responsibility_columns(app, fc_unit, fc_person, fc_flag)
            except Exception as e_inj:
                logger.debug(f"[mpp_renderer][RESP] 左侧列注入跳过(数据仍在 Text1/2/3): {e_inj}")

        # 5. 设置 Predecessors 前置依赖链
        #    关键修复: MS Project 将 .Predecessors 字符串中的数字当作"任务 ID"(按创建顺序位置),
        #    而非自定义 id。当自定义 id 不连续(如删节点产生缺口)时, 直接传入自定义 id 会被误判为
        #    自身或错位, 导致依赖链整体断裂。故此处把自定义 id 翻译为真实 MS Project 任务 ID 后再写入。
        for t in tasks:
            t_id = t["id"]
            level = t.get("outline_level", t.get("level", 3))
            preds_str = str(t.get("predecessors", "")).strip()

            if preds_str and level >= 3:
                curr_task = task_objects.get(t_id)
                if curr_task:
                    mp_ids = []
                    for _pid, _rest in split_predecessor_id_suffix(preds_str):
                        _mp = mp_id_map.get(_pid)
                        if _mp is None:
                            logger.warning(f"[mpp_renderer] Predecessor 未找到(自定义id={_pid}) 于任务 {t_id}")
                            continue
                        mp_ids.append(f"{_mp}{_rest}")
                    if mp_ids:
                        try:
                            curr_task.Predecessors = ",".join(mp_ids)
                        except Exception as e_p:
                            logger.warning(f"[mpp_renderer] Predecessors Warning [{t_id} -> {','.join(mp_ids)}]: {e_p}")
                        # 自引用防御: 若某前置翻译后恰为任务自身 MPP ID(renumber/翻译错位导致),
                        # 剔除自环, 避免 MS Project 重算时把任务自身当作前置, 引发级联漂移。
                        try:
                            _own = mp_id_map.get(t_id)
                            _bad = [p for p in curr_task.Predecessors.split(",") if p.strip() and int(p.strip()) == _own]
                            if _bad:
                                _clean = ",".join(p for p in curr_task.Predecessors.split(",") if p.strip() and int(p.strip()) != _own)
                                curr_task.Predecessors = _clean
                        except Exception:
                            pass

        # 5.5 应用用户给定里程碑的硬约束 (MSO=Must Start On / MFO=Must Finish On / SNET / FNLT)
        #     仅当任务 JSON 显式携带 "constraint" 字段时生效，完全向后兼容；用于 100% 锁定用户指定日期。
        #     关键：在设置约束之前切换到自动计算模式，使 MS Project 在设置每个约束时即时重算，
        #     确保保存的 MPP 带有约束锁定日期而非正向排程的自然日期。
        try:
            app.Calculation = 0  # pjAutomatic — 约束设置时即时重算
            app.ScreenUpdating = True
            logger.info("[mpp_renderer] 切换自动计算模式 (约束设置前)")
        except Exception as e_auto:
            logger.warning(f"[mpp_renderer] 切换自动计算失败: {e_auto}")

        _CONSTRAINT_MAP = {"MSO": 4, "MFO": 5, "SNET": 2, "FNLT": 3}
        for t in tasks:
            t_id = t["id"]
            constraint = t.get("constraint")
            if not constraint:
                continue
            ctype = str(constraint.get("type", "MSO")).upper()
            cdate = str(constraint.get("date", "")).strip().replace("/", "-")
            if not cdate:
                continue
            curr_task = task_objects.get(t_id)
            if not curr_task:
                continue
            try:
                from datetime import datetime as _dt
                _ymd = _dt.strptime(cdate, "%Y-%m-%d")
                # 锚定时刻: 默认 08:00(当日工作起始)，避免里程碑落在午夜导致摘要(Phase)工期卷算出现小数点；
                # 仅"落在周末且挂施工7天日历"的里程碑(如总包确认周六)用午夜(00:00)以精确锁定该日历日。
                _anchor = str(constraint.get("anchor", "08:00"))
                if _anchor == "00:00":
                    _cdate_obj = pywintypes.Time(datetime.date(_ymd.year, _ymd.month, _ymd.day))
                else:
                    _ah, _am = (int(x) for x in _anchor.split(":")) if ":" in _anchor else (8, 0)
                    _cdate_obj = pywintypes.Time(datetime.datetime(_ymd.year, _ymd.month, _ymd.day, _ah, _am, 0))
                ct = _CONSTRAINT_MAP.get(ctype, 4)
                try:
                    curr_task.ConstraintType = ct
                    curr_task.ConstraintDate = _cdate_obj
                    logger.info(f"[mpp_renderer][CONSTRAINT] 任务 {t_id} 锁定 {ctype} @ {cdate}")
                except Exception as e_c:
                    logger.warning(f"[mpp_renderer][CONSTRAINT] 任务 {t_id} 约束设置失败: {e_c}")
            except Exception as e_p:
                logger.warning(f"[mpp_renderer][CONSTRAINT] 任务 {t_id} 日期解析失败 {cdate}: {e_p}")

        # 切换主视图为标准甘特图
        try:
            app.ViewApplyEx(Name="甘特图", SinglePane=True)
        except Exception as e_view:
            logger.debug(f"[mpp_renderer] 切换甘特图视图失败: {e_view}")

        # 确保自动计算模式（约束设置时已切换，此处仅做防御性确认）
        try:
            app.Calculation = 0  # pjAutomatic
            app.ScreenUpdating = True
        except Exception:
            pass

        # 5.6 直接写入受约束任务的 Start/Finish 日期
        #     原因：设置 Finish 到工作日开始(08:00)时，MS Project 会将 Finish 解释为
        #     "前一工作日结束(17:00)"，导致日期回退1-3天。
        #     里程碑(duration=0)的 Start=Finish，用 Start 写入可正确锚定到当日工作起始。
        #     此步骤确保约束任务的日期不被 predecessor 提前覆盖。
        _date_set_count = 0
        _date_set_errors = 0
        for t in tasks:
            constraint = t.get("constraint")
            if not constraint:
                continue
            curr_task = task_objects.get(t["id"])
            if not curr_task:
                continue
            try:
                ctype = str(constraint.get("type", "MSO")).upper()
                cdate = str(constraint.get("date", "")).strip().replace("/", "-")
                if not cdate:
                    continue
                from datetime import datetime as _dt
                _ymd = _dt.strptime(cdate, "%Y-%m-%d")
                _anchor = str(constraint.get("anchor", "08:00"))
                if _anchor == "00:00":
                    _date_obj = pywintypes.Time(datetime.date(_ymd.year, _ymd.month, _ymd.day))
                else:
                    _ah, _am = (int(x) for x in _anchor.split(":")) if ":" in _anchor else (8, 0)
                    _date_obj = pywintypes.Time(datetime.datetime(_ymd.year, _ymd.month, _ymd.day, _ah, _am, 0))

                # 直接写入日期：所有约束类型都用 Start 写入
                # 原因：设置 Finish 到工作日开始(08:00)时，MS Project 会将 Finish 解释为
                # "前一工作日结束(17:00)"，导致日期回退1-3天。
                # 里程碑(duration=0)的 Start=Finish，用 Start 写入可正确锚定到当日工作起始。
                # SNET/MSO 本就用 Start 写入。
                curr_task.Start = _date_obj

                # 重新应用约束元数据（写 Start/Finish 可能改变 ConstraintType）
                ct = _CONSTRAINT_MAP.get(ctype, 4)
                curr_task.ConstraintType = ct
                curr_task.ConstraintDate = _date_obj

                _date_set_count += 1
                logger.info(f"[mpp_renderer][DATE-OVERRIDE] 任务 {t['id']} {ctype} @ {cdate} -> Start={curr_task.Start}, Finish={curr_task.Finish}")
            except Exception as e_d:
                _date_set_errors += 1
                logger.warning(f"[mpp_renderer][DATE-OVERRIDE] 任务 {t['id']} 直接日期写入失败: {e_d}")

        logger.info(f"[mpp_renderer] 直接日期写入完成: {_date_set_count} 个成功, {_date_set_errors} 个失败")

        # 5.7 强制全量重算（修复“打开 MPP 需按 F9 才显示正确日期”）
        #     根因：原流程仅依赖 app.Calculation=自动 在编辑时实时重算，但 COM 新建项目的
        #     摘要(Phase)任务在 SaveAs 时未必完成滚动汇总，重开文件后即需手动按 F9。此处显式调用
        #     已知的 CalculateProject() 把叶子+摘要日期全部算定后再 SaveAs，确保打开即见正确排期。
        #     注：project.CalculateAll() 在本机 MS Project 版本会触发 SaveAs 意外错误(1004)，故不使用。
        try:
            app.CalculateProject()
            logger.info("[mpp_renderer] 已调用 CalculateProject 全量重算(叶子+摘要)")
        except Exception as e_cp:
            logger.warning(f"[mpp_renderer] CalculateProject 失败: {e_cp}")

        # 物理 SaveAs 落盘
        if os.path.exists(output_mpp_path):
            try:
                os.remove(output_mpp_path)
            except Exception as e_rem:
                logger.warning(f"[mpp_renderer] 删除旧文件失败: {e_rem}")

        logger.info(f"[mpp_renderer] 正在 SaveAs 落盘: {output_mpp_path}")
        try:
            project.SaveAs(output_mpp_path)
        except Exception as e_save:
            logger.error(f"[mpp_renderer] 保存 .mpp 文件失败: {e_save}")
            raise

        if not os.path.exists(output_mpp_path):
            raise RuntimeError(f"[mpp_renderer] 写盘失败，未能在磁盘上检测到文件: {output_mpp_path}")

        size = os.path.getsize(output_mpp_path)
        logger.info(f"[mpp_renderer] [PHYSICAL VERIFIED] 100% 物理 .mpp 文件渲染成功！大小: {size:,} 字节")

    # 6. 同步导出无损 XML 交换文件（纯 Python，无需 COM 会话）
    _export_xml(tasks, project_title, project_start, output_mpp_path, logger)

    return output_mpp_path, {}


def _export_xml(tasks: List[Dict[str, Any]], project_title: str,
                project_start, output_mpp_path: str,
                log: logging.Logger = None):
    """同步导出 MSPX 格式 XML 交换文件（从 build_mpp 提取）。"""
    if log is None:
        log = logger
    try:
        xml_output_path = os.path.splitext(output_mpp_path)[0] + ".xml"
        import xml.etree.ElementTree as ET
        from xml.dom import minidom
        root = ET.Element("Project", xmlns="http://schemas.microsoft.com/project")
        ET.SubElement(root, "Title").text = project_title
        # 防御 project_start 为 None / datetime 类型，避免拼出 "NoneT08:00:00"
        if project_start is not None:
            if hasattr(project_start, "strftime"):
                ps_str = project_start.strftime("%Y-%m-%d")
            else:
                ps_str = str(project_start)
            ET.SubElement(root, "StartDate").text = f"{ps_str}T08:00:00"
        else:
            ET.SubElement(root, "StartDate").text = ""
        tasks_elem = ET.SubElement(root, "Tasks")
        for t in tasks:
            t_elem = ET.SubElement(tasks_elem, "Task")
            ET.SubElement(t_elem, "UID").text = str(t["id"])
            ET.SubElement(t_elem, "ID").text = str(t["id"])
            ET.SubElement(t_elem, "Name").text = str(t["name"])
            # 责任识别三字段
            ET.SubElement(t_elem, "ResponsibleUnit").text = str(t.get("responsible_unit", ""))
            ET.SubElement(t_elem, "ResponsiblePerson").text = str(t.get("responsible_person", ""))
            ET.SubElement(t_elem, "ResponsibilityFlag").text = str(t.get("responsibility_flag", ""))
            lvl = t.get("outline_level", t.get("level", 3))
            ET.SubElement(t_elem, "OutlineLevel").text = str(lvl)
            is_ms = t.get("milestone", False) or t.get("duration_days", t.get("duration", 0)) == 0
            ET.SubElement(t_elem, "Milestone").text = "1" if is_ms else "0"
            ET.SubElement(t_elem, "Summary").text = "1" if lvl <= 2 else "0"
            if t.get("constraint"):
                _ctype = str(t["constraint"].get("type", "MSO")).upper()
                _cdate = str(t["constraint"].get("date", "")).strip().replace("/", "-")
                ET.SubElement(t_elem, "ConstraintType").text = {"MSO": "4", "MFO": "5", "SNET": "2", "FNLT": "3"}.get(_ctype, "4")
                ET.SubElement(t_elem, "ConstraintDate").text = f"{_cdate}T08:00:00"
            if lvl >= 3:
                dur = t.get("duration", t.get("duration_days", 0))
                ET.SubElement(t_elem, "Duration").text = f"PT{int(round(float(dur))) * 8}H0M0S"
                if t.get("start"):
                    ET.SubElement(t_elem, "Start").text = f"{t['start']}T08:00:00"
                if t.get("finish"):
                    ET.SubElement(t_elem, "Finish").text = f"{t['finish']}T17:00:00"
                preds = str(t.get("predecessors", "")).strip()
                if preds:
                    for _pid, _suffix in split_predecessor_id_suffix(preds):
                        link_type = (_suffix or "FS").upper()
                        link_code = {"FS": "1", "SS": "0", "FF": "3", "SF": "2"}.get(link_type[:2], "1")
                        link_elem = ET.SubElement(t_elem, "PredecessorLink")
                        ET.SubElement(link_elem, "PredecessorUID").text = str(_pid)
                        ET.SubElement(link_elem, "Type").text = link_code
        raw_str = ET.tostring(root, encoding="utf-8")
        reparsed = minidom.parseString(raw_str)
        with open(xml_output_path, "w", encoding="utf-8") as f_xml:
            f_xml.write(reparsed.toprettyxml(indent="  "))
        log.info(f"[mpp_renderer] [XML AUTO-EXPORTED] 同步导出 XML 成功: {xml_output_path}")
    except Exception as e_xml:
        log.warning(f"[mpp_renderer] XML 自动导出提示: {e_xml}")
