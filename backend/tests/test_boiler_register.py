"""锅炉登记入口的判定规则、并发保护与历史数据留存测试。"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.boiler import CURRENT_RULE, BoilerService
from app.store import store

client = TestClient(app)

VALID_VALUES = {
    "设备编号": "BOIL-9001",
    "设备名称": "测试燃气蒸汽锅炉",
    "额定蒸发量": "2",
    "工作压力": "1.25",
    "使用场所": "测试锅炉房",
}


@pytest.fixture(autouse=True)
def restore_boiler_table():
    """每个用例跑完把锅炉台账还原，互不影响。"""
    original = copy.deepcopy(store.rows("boiler"))
    yield
    store._tables["boiler"] = original


def register(values: dict) -> dict:
    response = client.post("/api/boiler", json={"values": values})
    assert response.status_code == 200
    return response.json()


def test_missing_required_fields_rejected():
    payload = {key: value for key, value in VALID_VALUES.items() if key != "工作压力"}
    result = register(payload)
    assert result["ok"] is False
    assert "缺少必填字段" in result["message"]
    assert "工作压力" in result["message"]


def test_duplicate_code_rejected():
    result = register({**VALID_VALUES, "设备编号": "BOIL-0001"})
    assert result["ok"] is False
    assert "BOIL-0001" in result["message"]
    assert "重复" in result["message"]


def test_over_threshold_pressure_rejected():
    result = register({**VALID_VALUES, "工作压力": "5.0"})
    assert result["ok"] is False
    assert "阈值" in result["message"]
    assert str(CURRENT_RULE.max_pressure_mpa) in result["message"]


def test_invalid_evaporation_rejected():
    result = register({**VALID_VALUES, "额定蒸发量": "若干"})
    assert result["ok"] is False
    assert "额定蒸发量" in result["message"]


def test_all_problems_reported_by_one_rule():
    """编号重复、压力超阈值、必填缺失命中同一条判定规则，原因一次性说清。"""
    result = register({"设备编号": "BOIL-0001", "工作压力": "9.9"})
    assert result["ok"] is False
    assert "缺少必填字段" in result["message"]
    assert "重复" in result["message"]
    assert "阈值" in result["message"]


def test_create_success_lands_in_ledger_detail_and_overview():
    before = client.get("/api/boiler").json()["total"]
    result = register(VALID_VALUES)
    assert result["ok"] is True
    entry = result["entry"]
    assert entry["rule_version"] == CURRENT_RULE.version
    assert entry["pressure_limit_mpa"] == CURRENT_RULE.max_pressure_mpa

    listed = client.get("/api/boiler", params={"keyword": "BOIL-9001"}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["设备编号"] == "BOIL-9001"

    detail = client.get(f"/api/boiler/{entry['id']}").json()
    assert detail["设备编号"] == "BOIL-9001"
    assert detail["rule_version"] == CURRENT_RULE.version

    # 台账与运营概览取同一份数据：在册台数一致，且登记后立刻可见。
    overview = client.get("/api/overview").json()
    boiler_module = next(item for item in overview["modules"] if item["name"] == "boiler")
    assert boiler_module["created"] == client.get("/api/boiler").json()["total"] == before + 1


def test_concurrent_same_code_only_one_succeeds():
    service = BoilerService()
    values = {**VALID_VALUES, "设备编号": "BOIL-9002"}

    def attempt(_: int) -> bool:
        entry, _ = service.create_entry(values)
        return entry is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(16)))

    assert outcomes.count(True) == 1
    codes = [row for row in store.rows("boiler") if row.get("设备编号") == "BOIL-9002"]
    assert len(codes) == 1


def test_second_submit_of_same_code_rejected():
    first = register({**VALID_VALUES, "设备编号": "BOIL-9003"})
    second = register({**VALID_VALUES, "设备编号": "BOIL-9003"})
    assert first["ok"] is True
    assert second["ok"] is False
    assert "重复" in second["message"]


def test_historical_rows_keep_registration_rule():
    """历史锅炉按登记时的口径留存：5.0 MPa 的 BOIL-0003 不被新阈值误判，新登记同压力则被拦。"""
    listed = client.get("/api/boiler", params={"keyword": "BOIL-0003"}).json()
    assert listed["total"] == 1
    historical = listed["items"][0]
    assert historical["工作压力"] == "5.0 MPa"
    assert historical["rule_version"] == "v1-2014"
    assert historical["pressure_limit_mpa"] == 9.8

    detail = client.get(f"/api/boiler/{historical['id']}").json()
    assert detail["设备编号"] == "BOIL-0003"

    rejected = register({**VALID_VALUES, "设备编号": "BOIL-9004", "工作压力": "5.0"})
    assert rejected["ok"] is False
    assert "阈值" in rejected["message"]

    # 新登记被拦之后，历史数据原样保留、不少不多。
    assert client.get("/api/boiler", params={"keyword": "BOIL-0003"}).json()["total"] == 1


def test_existing_queries_and_rule_endpoint():
    rule = client.get("/api/boiler/rule").json()
    assert rule["version"] == CURRENT_RULE.version
    assert rule["max_pressure_mpa"] == CURRENT_RULE.max_pressure_mpa

    export = client.get("/api/boiler/export").json()
    assert export["module"] == "boiler"
    assert export["total"] == client.get("/api/boiler").json()["total"]

    paged = client.get("/api/boiler", params={"status": "停炉检修"}).json()
    assert all(item["status"] == "停炉检修" for item in paged["items"])
