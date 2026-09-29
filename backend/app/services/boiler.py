"""锅炉设备业务规则：登记校验、状态流转、字段筛选口径都收在这里。

登记校验口径（编号唯一、额定蒸发量、工作压力阈值）集中在本模块，调整阈值后：
- 新登记的锅炉按新一套口径判定，并在记录上快照登记时的口径版本与阈值；
- 既有历史锅炉数据保留登记当时的口径，不会被新校验误判成非法。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "boiler"

# 登记校验口径：调整这里的阈值即切换到新一套判定规则。
RULE_VERSION = "v2026.09"
PRESSURE_MAX_MPA = 2.5          # 工作压力登记阈值（MPa），超过该阈值不予登记
EVAPORATION_MIN_TPH = 0.1        # 额定蒸发量登记下限（t/h），须为正数
REQUIRED_FIELDS = ["设备编号", "设备名称", "额定蒸发量", "工作压力"]

STATUS_ORDER = ["待投用", "在用运行", "停炉检修", "已报废"]
ACTION_RULES = {"办理投用": "在用运行", "安排检修": "停炉检修", "报废设备": "已报废"}
NEGATIVE_ACTIONS = []

# 登记并发锁：同一设备编号并发提交时，只允许一个请求登记成功。
_create_lock = threading.Lock()


def _parse_positive_number(value: Any) -> float | None:
    """把输入解析成正数；无法解析或不是正数时返回 None。"""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class BoilerService:
    def current_rule(self) -> dict[str, Any]:
        """返回当前登记校验口径，供登记入口展示阈值与必填项。"""
        return {
            "version": RULE_VERSION,
            "pressure_max_mpa": PRESSURE_MAX_MPA,
            "evaporation_min_tph": EVAPORATION_MIN_TPH,
            "required_fields": list(REQUIRED_FIELDS),
        }

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
        """登记一条锅炉设备。

        按同一条校验规则逐项检查必填项、额定蒸发量、工作压力与编号重复，
        所有不通过的原因一次性返回；并发提交同一编号时只允许成功一次。
        """
        errors: list[str] = []

        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            errors.append("必填字段缺失：" + "、".join(missing))

        evaporation_raw = values.get("额定蒸发量")
        if evaporation_raw is not None and str(evaporation_raw).strip():
            evaporation = _parse_positive_number(evaporation_raw)
            if evaporation is None:
                errors.append(f"额定蒸发量「{evaporation_raw}」不是有效正数（单位 t/h）")
            elif evaporation < EVAPORATION_MIN_TPH:
                errors.append(
                    f"额定蒸发量 {evaporation:g} t/h 低于登记下限 {EVAPORATION_MIN_TPH:g} t/h"
                )

        pressure_raw = values.get("工作压力")
        if pressure_raw is not None and str(pressure_raw).strip():
            pressure = _parse_positive_number(pressure_raw)
            if pressure is None:
                errors.append(f"工作压力「{pressure_raw}」不是有效正数（单位 MPa）")
            elif pressure > PRESSURE_MAX_MPA:
                errors.append(
                    f"工作压力 {pressure:g} MPa 超过登记阈值 {PRESSURE_MAX_MPA:g} MPa，不予登记"
                )

        code = str(values.get("设备编号") or "").strip()
        with _create_lock:
            if code and any(
                str(row.get("设备编号") or "").strip() == code for row in store.rows(MODULE)
            ):
                errors.append(f"设备编号「{code}」已登记，不能重复登记")
            if errors:
                return None, errors

            rows = store.rows(MODULE)
            entry: dict[str, Any] = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "status": STATUS_ORDER[0],
                "pending": True,
                "abnormal": False,
                # 登记口径快照：新登记按当前阈值判定，历史数据保留登记当时的口径
                "校验口径版本": RULE_VERSION,
                "工作压力阈值": PRESSURE_MAX_MPA,
            }
            for field in ("设备编号", "设备名称", "额定蒸发量", "工作压力", "使用场所", "投用日期", "下次检验日"):
                raw = values.get(field)
                if raw is not None and str(raw).strip():
                    entry[field] = str(raw).strip()
            if code:
                entry["设备编号"] = code
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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"锅炉设备已{action}"
