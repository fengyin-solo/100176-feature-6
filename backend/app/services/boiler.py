"""锅炉设备业务规则：状态流转、登记校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from app.store import store

MODULE = "boiler"
REQUIRED_FIELDS = ["设备编号", "设备名称", "额定蒸发量", "工作压力"]
OPTIONAL_FIELDS = ["使用场所", "投用日期", "下次检验日"]
STATUS_ORDER = ["待投用", "在用运行", "停炉检修", "已报废"]
ACTION_RULES = {"办理投用": "在用运行", "安排检修": "停炉检修", "报废设备": "已报废"}
NEGATIVE_ACTIONS: list[str] = []


@dataclass(frozen=True)
class RegisterRule:
    """一版登记校验口径：调整阈值时另起新版本，历史数据仍按登记时的版本留存。"""

    version: str
    max_pressure_mpa: float


# 校验口径沿革：旧版允许到 9.8 MPa，现行口径收紧到 3.82 MPa。
# 之后再调整就追加新规则并改 CURRENT_RULE，不要回头改历史版本。
RULE_HISTORY = [RegisterRule(version="v1-2014", max_pressure_mpa=9.8)]
CURRENT_RULE = RegisterRule(version="v2-2026", max_pressure_mpa=3.82)

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def parse_number(value: Any) -> float | None:
    """从「1.25」「1.25 MPa」这类写法里取出数值；取不出来返回 None。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _NUMBER_PATTERN.search(str(value or ""))
    return float(match.group()) if match else None


def validate_registration(
    values: dict[str, Any],
    rows: list[dict[str, Any]],
    rule: RegisterRule = CURRENT_RULE,
) -> list[str]:
    """登记判定规则：必填、编号唯一、蒸发量与压力逐项过一遍，问题一次性说清。

    必填缺失、编号重复、压力超阈值都走这一条规则，返回全部命中的原因。
    """
    problems: list[str] = []
    missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
    if missing:
        problems.append(f"缺少必填字段：{'、'.join(missing)}")

    code = str(values.get("设备编号") or "").strip()
    if code and any(str(row.get("设备编号") or "").strip() == code for row in rows):
        problems.append(f"设备编号 {code} 已在台账中，不能重复登记")

    evaporation_raw = str(values.get("额定蒸发量") or "").strip()
    if evaporation_raw:
        evaporation = parse_number(evaporation_raw)
        if evaporation is None or evaporation <= 0:
            problems.append("额定蒸发量需为大于 0 的数值（单位 t/h）")

    pressure_raw = str(values.get("工作压力") or "").strip()
    if pressure_raw:
        pressure = parse_number(pressure_raw)
        if pressure is None or pressure <= 0:
            problems.append("工作压力需为大于 0 的数值（单位 MPa）")
        elif pressure > rule.max_pressure_mpa:
            problems.append(
                f"工作压力 {pressure:g} MPa 超过现行口径 {rule.version} 的阈值 {rule.max_pressure_mpa:g} MPa"
            )
    return problems


class BoilerService:
    def __init__(self) -> None:
        # 查重与落库放在同一把锁里：同一编号并发登记只放行一单。
        self._create_lock = threading.Lock()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        with self._create_lock:
            rows = store.rows(MODULE)
            problems = validate_registration(values, rows)
            if problems:
                return None, problems
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                text = str(values.get(field) or "").strip()
                if text:
                    entry[field] = text
            entry["status"] = STATUS_ORDER[0]
            entry["设备状态"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            # 把登记当时的校验口径固化到台账上，日后口径调整不回溯误判历史数据。
            entry["rule_version"] = CURRENT_RULE.version
            entry["pressure_limit_mpa"] = CURRENT_RULE.max_pressure_mpa
            rows.append(entry)
            return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"锅炉设备 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于锅炉设备可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["设备状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"锅炉设备已{action}"
