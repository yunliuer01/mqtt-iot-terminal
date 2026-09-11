# -*- coding: utf-8 -*-
"""映射配置加载工具

供 relay_terminal.py / terminal_modbus.py 等 Python 终端脚本 import 使用，
把 Web 管理界面（web/app.py）创建的 mapping.json 读取为字典。

用法：
    from web.mapping_loader import load_mapping, get_relay_group, get_modbus_sensor

    cfg = load_mapping()
    group = get_relay_group("relay8_lfx")
    sensor = get_modbus_sensor("modbus-th-01")
"""
import json
import os
from pathlib import Path

# 兼容两种 import 场景：从项目根目录或被其他目录 import
_BASE = Path(__file__).parent.resolve()
MAPPING_FILE = _BASE / "static" / "mapping.json"


def load_mapping(path: str = None) -> dict:
    """读取 web/static/mapping.json（或指定 path），返回完整配置字典"""
    f = Path(path) if path else MAPPING_FILE
    if not f.exists():
        raise FileNotFoundError(f"映射配置文件不存在: {f}")
    with open(f, "r", encoding="utf-8") as fp:
        return json.load(fp)


def get_relay_group(group_id: str, path: str = None) -> dict:
    """按 id 返回继电器组配置；找不到返回 None"""
    cfg = load_mapping(path)
    for g in cfg.get("relay_groups", []):
        if g.get("id") == group_id:
            return g
    return None


def get_modbus_sensor(sensor_id: str, path: str = None) -> dict:
    """按 id 返回 Modbus 传感器配置；找不到返回 None"""
    cfg = load_mapping(path)
    for s in cfg.get("modbus_sensors", []):
        if s.get("id") == sensor_id:
            return s
    return None


def list_relay_groups(path: str = None) -> list:
    """返回所有继电器组 id + name 列表"""
    cfg = load_mapping(path)
    return [{"id": g.get("id"), "name": g.get("name"), "device_id": g.get("device_id")}
            for g in cfg.get("relay_groups", [])]


def list_modbus_sensors(path: str = None) -> list:
    """返回所有 Modbus 传感器 id + name 列表"""
    cfg = load_mapping(path)
    return [{"id": s.get("id"), "name": s.get("name"), "device_id": s.get("device_id")}
            for s in cfg.get("modbus_sensors", [])]
