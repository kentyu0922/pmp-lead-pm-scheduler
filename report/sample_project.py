"""Baseline WBS for a 1,000 sqm Grade-A commercial office fit-out.

The sequence follows the trade logic enforced by the scheduler rule set:
Demolition -> MEP 1st Fix -> Partitions -> Finishes -> IAQ Gate -> Move-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

from .cpm_engine import Task, WorkCalendar


PROJECT = {
    "code": "LPM-2026-0417",
    "title_zh": "商業辦公室裝修工程",
    "title_en": "Commercial Office Fit-out",
    "client": "Meridian Capital Partners",
    "site_zh": "中環甲級商廈 32 樓 · 淨面積約 1,000 平方米",
    "site_en": "Grade-A Tower, 32/F · NFA approx. 1,000 sqm",
    "procurement": "Design & Build (D&B)",
    "baseline": "Baseline Rev. B",
    "calendar_zh": "六天工作週（週一至週六），扣除公眾假期",
    "calendar_en": "6-day week (Mon–Sat), public holidays excluded",
    "prepared_by": "AI Lead PM Scheduler · CPM Engine",
    "data_date": date(2026, 9, 4),
}

PHASES: Dict[str, Dict[str, str]] = {
    "P1": {"zh": "前期準備與採購", "en": "Pre-construction & Procurement"},
    "P2": {"zh": "拆除及清場", "en": "Demolition & Strip-out"},
    "P3": {"zh": "機電一次配管", "en": "MEP 1st Fix"},
    "P4": {"zh": "間隔與天花", "en": "Partitions & Ceilings"},
    "P5": {"zh": "機電二次配管", "en": "MEP 2nd Fix"},
    "P6": {"zh": "裝飾工程", "en": "Finishes"},
    "P7": {"zh": "木作與傢俬", "en": "Joinery & Furniture"},
    "P8": {"zh": "測試調試、IAQ 及交付", "en": "T&C, IAQ Gate & Handover"},
}

# Public holidays intersecting the schedule window (illustrative).
HOLIDAYS = [
    date(2026, 10, 1),   # National Day
    date(2026, 10, 19),  # Chung Yeung Festival (observed)
    date(2026, 12, 25),  # Christmas Day
    date(2026, 12, 26),  # Boxing Day
    date(2027, 1, 1),    # New Year's Day
    date(2027, 2, 8),    # Lunar New Year
    date(2027, 2, 9),
    date(2027, 2, 10),
]

PROJECT_START = date(2026, 10, 5)


def _t(id_, wbs, zh, en, phase, dur, preds=(), trade="", milestone=False, risks=()):
    return Task(id=id_, wbs=wbs, name_zh=zh, name_en=en, phase=phase, duration=dur,
                predecessors=list(preds), trade=trade, milestone=milestone, risk_ids=list(risks))


def build_tasks() -> List[Task]:
    return [
        # P1 Pre-construction & Procurement
        _t("M0", "1.1", "合約簽署及啟動會議", "Contract Award & Kick-off", "P1", 0, (), "PM", True),
        _t("A1", "1.2", "現場勘查及現況紀錄", "Site Survey & Existing Condition Report", "P1", 3, ("M0",), "PM"),
        _t("A2", "1.3", "施工圖及細部設計", "Design Development & Shop Drawings", "P1", 12, ("A1",), "Design"),
        _t("A3", "1.4", "業主及大廈管理處審批", "Landlord & Building Management Approval", "P1", 8, ("A2",), "PM", risks=("R05",)),
        _t("A4", "1.5", "消防及法定圖則申報", "Fire Services & Statutory Submission", "P1", 15, ("A2",), "Consultant", risks=("R01",)),
        _t("A5", "1.6", "進場動員及圍板", "Site Mobilisation & Hoarding", "P1", 3, ("A3",), "Main Con."),
        _t("A6", "1.7", "長交期採購：玻璃間隔及木作", "Long-lead: Glass Partition & Joinery", "P1", 30, ("A2",), "Procurement", risks=("R02",)),
        _t("A7", "1.8", "長交期採購：活動傢俬", "Long-lead: Loose Furniture", "P1", 45, ("A2",), "Procurement", risks=("R03",)),
        _t("A8", "1.9", "長交期採購：燈具及影音設備", "Long-lead: Lighting & AV Equipment", "P1", 25, ("A2",), "Procurement"),
        _t("M1", "1.10", "法定審批取得", "Statutory Approvals Obtained", "P1", 0, ("A3", "A4"), "PM", True),
        # P2 Demolition
        _t("B1", "2.1", "保護工程及拆除", "Protection Works & Strip-out", "P2", 5, ("A5",), "Demolition", risks=("R04",)),
        _t("B2", "2.2", "廢料清運及地台修補", "Debris Removal & Slab Making Good", "P2", 3, ("B1",), "Demolition", risks=("R12",)),
        _t("B3", "2.3", "放線定位", "Setting Out", "P2", 2, ("B2",), "Main Con."),
        # P3 MEP 1st Fix
        _t("C1", "3.1", "消防噴淋改位", "Sprinkler Relocation", "P3", 8, ("B3", "M1"), "FS", risks=("R06",)),
        _t("C2", "3.2", "空調風管及 VAV 箱", "HVAC Ductwork & VAV Boxes", "P3", 10, ("B3",), "HVAC"),
        _t("C3", "3.3", "電力線槽及佈線", "Electrical Containment & Cabling", "P3", 10, ("B3",), "Electrical", risks=("R11",)),
        _t("C4", "3.4", "弱電及數據線槽", "ELV & Data Containment", "P3", 8, ("B3",), "ELV"),
        _t("C5", "3.5", "給排水預埋（茶水間及濕區）", "Plumbing Rough-in (Pantry & Wet Areas)", "P3", 5, ("B3",), "Plumbing"),
        # P4 Partitions & Ceilings
        _t("D1", "4.1", "輕鋼架間牆及封板", "Drywall Framing & Boarding", "P4", 10, ("C1", "C2", "C3", "C4"), "Drywall"),
        _t("D2", "4.2", "天花龍骨及燈槽", "Ceiling Grid & Bulkheads", "P4", 8, ("D1",), "Ceiling"),
        _t("D3", "4.3", "玻璃間隔安裝", "Glass Partition Installation", "P4", 8, ("D1", "A6"), "Glazing"),
        _t("D4", "4.4", "地台找平", "Floor Screed & Levelling", "P4", 4, ("D1", "C5"), "Main Con."),
        # P5 MEP 2nd Fix
        _t("E1", "5.1", "燈具及天花設備安裝", "Lighting & Ceiling Devices", "P5", 6, ("D2", "A8"), "Electrical", risks=("R07",)),
        _t("E2", "5.2", "開關插座及電力終端", "Wiring Devices & Power Outlets", "P5", 5, ("F1",), "Electrical", risks=("R07",)),
        _t("E3", "5.3", "火警探測器及噴淋頭", "Fire Alarm Devices & Sprinkler Heads", "P5", 5, ("D2",), "FS"),
        _t("E4", "5.4", "風口安裝及風量平衡", "AC Diffusers & Air Balancing", "P5", 4, ("D2",), "HVAC"),
        _t("E5", "5.5", "數據跳線終端及測試", "Data Cabling Termination & Test", "P5", 5, ("D2",), "ELV"),
        _t("M2", "5.6", "天花封閉", "Ceiling Close-up", "P5", 0, ("E1", "E3", "E4", "E5"), "PM", True),
        # P6 Finishes
        _t("F1", "6.1", "批盪及油漆（底漆及面漆）", "Skim Coat & Paint (1st & 2nd Coat)", "P6", 8, ("D2", "D3"), "Painting"),
        _t("F2", "6.2", "地毯及膠地板", "Carpet Tiles & Vinyl Flooring", "P6", 5, ("F1", "D4"), "Flooring"),
        _t("F3", "6.3", "茶水間及濕區瓷磚", "Pantry & Wet Area Tiling", "P6", 5, ("D4",), "Tiling"),
        _t("F4", "6.4", "特色牆及牆面裝飾", "Feature Wall & Wall Finishes", "P6", 6, ("F1",), "Finishes", risks=("R09",)),
        # P7 Joinery & Furniture
        _t("G1", "7.1", "固定木作安裝", "Built-in Joinery Installation", "P7", 8, ("F1", "A6"), "Joinery", risks=("R09",)),
        _t("G2", "7.2", "門、五金及標識", "Doors, Hardware & Signage", "P7", 4, ("G1",), "Joinery"),
        _t("G3", "7.3", "活動傢俬進場及安裝", "Loose Furniture Delivery & Set-up", "P7", 5, ("F2", "G2", "A7"), "Furniture", risks=("R03", "R12")),
        _t("G4", "7.4", "影音及 IT 設備安裝", "AV & IT Equipment Installation", "P7", 4, ("G3", "E5"), "AV/IT"),
        # P8 T&C, IAQ & Handover
        _t("H1", "8.1", "修補及深層清潔", "Touch-up & Deep Cleaning", "P8", 3, ("G3", "F4", "F3"), "Main Con."),
        _t("H2", "8.2", "機電測試及調試", "MEP Testing & Commissioning", "P8", 5, ("M2", "E2"), "MEP", ),
        _t("H3", "8.3", "消防驗收", "Fire Services Inspection", "P8", 3, ("H2",), "FS", risks=("R10",)),
        _t("H4", "8.4", "室內空氣質素檢測（IAQ 閘門）", "IAQ Test (Air Quality Gate)", "P8", 5, ("H1", "H2"), "Consultant", risks=("R08",)),
        _t("H5", "8.5", "缺陷檢查及修正", "Defects Inspection & Rectification", "P8", 4, ("H1",), "Main Con."),
        _t("M3", "8.6", "實際完工及交付", "Practical Completion & Handover", "P8", 0, ("H3", "H4", "H5", "G4"), "PM", True),
        _t("M4", "8.7", "客戶入伙", "Client Move-in", "P8", 0, ("M3",), "Client", True),
    ]


@dataclass
class Risk:
    id: str
    title_zh: str
    title_en: str
    probability: int          # 1-5
    impact: int               # 1-5
    delay_days: int           # schedule impact if realised (working days)
    response_zh: str
    owner: str
    task_ids: List[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return self.probability * self.impact

    @property
    def level(self) -> str:
        s = self.score
        return "high" if s >= 15 else "medium" if s >= 8 else "low"


def build_risks() -> List[Risk]:
    return [
        Risk("R01", "消防法定申報審批延誤", "Statutory fire submission approval delay", 4, 5, 10,
             "提前預審；準備替代噴淋方案；預留審批浮時", "Consultant", ["A4"]),
        Risk("R02", "玻璃間隔及木作進口船期延誤", "Glass partition / joinery shipment delay", 3, 4, 7,
             "下單前鎖定船期；分批出貨；本地備選供應商", "Procurement", ["A6"]),
        Risk("R03", "活動傢俬清關延誤", "Loose furniture customs clearance delay", 3, 3, 5,
             "提早 2 週下單；預先報關；臨時傢俬方案", "Procurement", ["A7", "G3"]),
        Risk("R04", "拆除時發現隱蔽狀況（石棉／結構）", "Hidden conditions found during strip-out", 2, 5, 8,
             "開工前局部開孔勘查；備用檢測承辦商", "Main Con.", ["B1"]),
        Risk("R05", "業主審批要求修改設計", "Landlord approval requires design revision", 3, 3, 5,
             "早期與管理處預審；同步提交多方案", "PM", ["A3"]),
        Risk("R06", "噴淋停水窗口受大廈限制", "Sprinkler shutdown windows restricted", 4, 3, 4,
             "預訂夜間及週末停水時段；分區施工", "FS", ["C1"]),
        Risk("R07", "機電二次配管工序擠壓、人手不足", "Trade congestion / labour shortage at 2nd fix", 3, 3, 4,
             "分區交接計劃；提前鎖定分判人手", "MEP", ["E1", "E2"]),
        Risk("R08", "IAQ 檢測不合格需沖洗", "IAQ test failure requiring flush-out", 2, 4, 5,
             "選用低 VOC 材料；完工前 72 小時通風沖洗", "Consultant", ["H4"]),
        Risk("R09", "裝飾階段客戶變更要求", "Client change requests during finishes", 4, 3, 6,
             "設計凍結日期；變更影響評估流程", "PM", ["F4", "G1"]),
        Risk("R10", "消防驗收改期", "Fire Services inspection rescheduled", 3, 4, 5,
             "提前 3 週預約；預驗收自檢", "FS", ["H3"]),
        Risk("R11", "主電掣接駁停電安排", "Power shutdown for main switch tie-in", 2, 3, 2,
             "與管理處協調夜間停電；備用發電機", "Electrical", ["C3"]),
        Risk("R12", "貨梯及吊運預約受限", "Goods lift / hoist booking constraints", 3, 2, 2,
             "每週預訂貨梯時段；夜間送貨", "Main Con.", ["B2", "G3"]),
    ]


def build_calendar() -> WorkCalendar:
    return WorkCalendar(project_start=PROJECT_START, workdays=(0, 1, 2, 3, 4, 5), holidays=HOLIDAYS)
