# -*- coding: utf-8 -*-
"""Web 映射管理后台（Flask）

功能：
  - REST API 管理继电器通道 <-> 虚拟设备/物模型属性映射
  - REST API 管理 Modbus 温湿度传感器 <-> 虚拟设备映射
  - JSON 文件持久化，供 relay_terminal.py / modbus 采集终端读取

运行：
    python web/app.py
    浏览器打开 http://localhost:5000

依赖：
    pip install flask
"""
import json
import os
import queue
import sys
import threading
import time
import urllib.request
import urllib.error
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# ---- 实时 MQTT 数据缓存与 SSE 推送 ----
LIVE_Q = queue.Queue(maxsize=500)          # 后端订阅到的消息流
LIVE_CACHE = {}                            # 各设备最新属性快照
LIVE_CLIENTS = 0                           # 当前 SSE 连接数
LIVE_LAST_PING = time.time()

MQTT_BROKER = ("172.16.4.211", 9783)
MQTT_USER = "test"
MQTT_PASS = "123456"

HERE = Path(__file__).parent.resolve()
MAPPING_FILE = HERE / "static" / "mapping.json"

DEFAULT_MAPPING = {
    "version": "1.0",
    "updated_at": None,
    "relay_groups": [
        {
            "id": "relay8_lfx",
            "name": "8路继电器-lfx",
            "product_id": "relay8_lfx",
            "device_id": "RELAY8-TERM-01",
            "broker": {
                "host": "172.16.4.211",
                "port": 9783,
                "username": "test",
                "password": "123456"
            },
            "command": {
                "method": "write",
                "topic_template": "/{product_id}/{device_id}/service/cmd"
            },
            "channels": [
                {"ch": 1, "attr": "r1", "name": "开关1", "enabled": True},
                {"ch": 2, "attr": "r2", "name": "开关2", "enabled": True},
                {"ch": 3, "attr": "r3", "name": "开关3", "enabled": True},
                {"ch": 4, "attr": "r4", "name": "开关4", "enabled": True},
                {"ch": 5, "attr": "r5", "name": "开关5", "enabled": True},
                {"ch": 6, "attr": "r6", "name": "开关6", "enabled": True},
                {"ch": 7, "attr": "r7", "name": "开关7", "enabled": True},
                {"ch": 8, "attr": "r8", "name": "开关8", "enabled": True},
            ]
        },
        {
            "id": "relay4_lfx",
            "name": "4路继电器-lfx（ESP32-C3 实板）",
            "product_id": "relay4_lfx",
            "device_id": "7ce8b1c1a7fc",
            "broker": {
                "host": "172.16.4.211",
                "port": 9783,
                "username": "test",
                "password": "123456"
            },
            "command": {
                "method": "write",
                "topic_template": "/{product_id}/{device_id}/service/cmd"
            },
            "channels": [
                {"ch": 1, "attr": "r1", "name": "继电器1", "enabled": True},
                {"ch": 2, "attr": "r2", "name": "继电器2", "enabled": True},
                {"ch": 3, "attr": "r3", "name": "继电器3", "enabled": True},
                {"ch": 4, "attr": "r4", "name": "继电器4", "enabled": True},
            ]
        }
    ],
    "modbus_sensors": [
        {
            "id": "modbus-th-01",
            "name": "Modbus温湿度传感器",
            "device_id": "MODBUS-TERM-01",
            "product_id": "mqtt-iot",
            "slave_ip": "192.168.20.59",
            "slave_port": 5502,
            "slave_id": 1,
            "register_addr": "0x0005",
            "temperature_field": "temperature",
            "humidity_field": "humidity",
            "report_interval": 5,
            "enabled": True
        }
    ]
}


def _load() -> dict:
    if not MAPPING_FILE.exists():
        _save(DEFAULT_MAPPING)
    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        app.logger.warning("读取 %s 失败: %s，使用默认配置", MAPPING_FILE, e)
        data = DEFAULT_MAPPING.copy()
    # 自动补全缺失字段，保证向后兼容
    data.setdefault("version", "1.0")
    data.setdefault("relay_groups", [])
    data.setdefault("modbus_sensors", [])
    return data


def _save(data: dict):
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _resp(ok=True, data=None, msg=""):
    return jsonify({"ok": ok, "data": data, "msg": msg})


# ---- 实时数据：后端订阅 MQTT，通过 SSE 推给前端 ----
def _mqtt_start():
    if mqtt is None:
        app.logger.warning("paho-mqtt 未安装，实时数据流不可用")
        return

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            app.logger.info("SSE-MQTT 后端已连接 172.16.4.211:9783")
            topics = [
                ("/relay4_lfx/7ce8b1c1a7fc/property/post", 0),
                ("/relay4_lfx/7ce8b1c1a7fc/properties/report", 0),
                ("/+/+/properties/report", 0),
            ]
            client.subscribe(topics)
        else:
            app.logger.warning("SSE-MQTT 连接失败 rc=%s", rc)

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
            data = json.loads(payload)
        except Exception:
            data = payload
        packet = {
            "topic": msg.topic,
            "payload": data,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        LIVE_CACHE[msg.topic] = packet
        try:
            LIVE_Q.put(packet, block=False)
        except queue.Full:
            LIVE_Q.get_nowait()
            LIVE_Q.put(packet, block=False)

    def loop():
        client_id = f"web-dash-{int(time.time()*1000)}"
        # paho 2.x 需要 CallbackAPIVersion
        try:
            client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        except Exception:
            client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        while True:
            try:
                client.connect(*MQTT_BROKER, keepalive=60)
                client.loop_forever()
            except Exception as e:
                app.logger.warning("SSE-MQTT 后端连接异常：%s，5s 后重连", e)
                time.sleep(5)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


@app.route("/api/live")
def live_stream():
    """Server-Sent Events：把后端订阅到的 MQTT 消息实时推给前端"""
    def generate():
        global LIVE_CLIENTS
        LIVE_CLIENTS += 1
        app.logger.info("新增 SSE 客户端，当前 %d 个", LIVE_CLIENTS)
        # 先发一次当前缓存快照，前端立刻有数据
        snap = {k: v for k, v in LIVE_CACHE.items()}
        if snap:
            yield f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
        try:
            while True:
                packet = LIVE_Q.get(timeout=20)
                yield f"data: {json.dumps(packet, ensure_ascii=False)}\n\n"
        except queue.Empty:
            # 20 秒无数据发一次心跳，保持连接
            yield "event: ping\ndata: {}\n\n"
        finally:
            LIVE_CLIENTS -= 1
            app.logger.info("SSE 客户端断开，当前 %d 个", LIVE_CLIENTS)

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---- 静态首页 ----
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/dashboard")
def dashboard():
    return send_from_directory("static", "dashboard.html")


# ---- 映射 CRUD ----
@app.route("/api/mapping", methods=["GET"])
def get_mapping():
    return _resp(data=_load())


@app.route("/api/mapping", methods=["PUT"])
def put_mapping():
    body = request.get_json(silent=True) or {}
    if not body:
        return _resp(ok=False, msg="请求体为空"), 400
    # 基本结构校验
    if not isinstance(body.get("relay_groups", []), list):
        return _resp(ok=False, msg="relay_groups 必须是数组"), 400
    if not isinstance(body.get("modbus_sensors", []), list):
        return _resp(ok=False, msg="modbus_sensors 必须是数组"), 400
    _save(body)
    return _resp(data=body, msg="保存成功")


@app.route("/api/mapping/relay/<group_id>", methods=["PUT"])
def put_relay_group(group_id):
    body = request.get_json(silent=True) or {}
    body["id"] = group_id
    data = _load()
    groups = data.get("relay_groups", [])
    for i, g in enumerate(groups):
        if g.get("id") == group_id:
            groups[i] = body
            break
    else:
        groups.append(body)
    _save(data)
    return _resp(data=body, msg="继电器组保存成功")


@app.route("/api/mapping/relay/<group_id>", methods=["DELETE"])
def delete_relay_group(group_id):
    data = _load()
    groups = data.get("relay_groups", [])
    data["relay_groups"] = [g for g in groups if g.get("id") != group_id]
    _save(data)
    return _resp(msg="继电器组已删除")


@app.route("/api/mapping/modbus/<sensor_id>", methods=["PUT"])
def put_modbus_sensor(sensor_id):
    body = request.get_json(silent=True) or {}
    body["id"] = sensor_id
    data = _load()
    sensors = data.get("modbus_sensors", [])
    for i, s in enumerate(sensors):
        if s.get("id") == sensor_id:
            sensors[i] = body
            break
    else:
        sensors.append(body)
    _save(data)
    return _resp(data=body, msg="Modbus 传感器保存成功")


@app.route("/api/mapping/modbus/<sensor_id>", methods=["DELETE"])
def delete_modbus_sensor(sensor_id):
    data = _load()
    sensors = data.get("modbus_sensors", [])
    data["modbus_sensors"] = [s for s in sensors if s.get("id") != sensor_id]
    _save(data)
    return _resp(msg="Modbus 传感器已删除")


# ---- 可选：从 JetLinks 平台拉取设备/产品列表（用于下拉选择） ----
JETLINKS_BASE = "http://172.16.4.211:9000/api"
JETLINKS_USER = "admin5"
JETLINKS_PASS = "Admin@group5"


def _jetlinks_token():
    try:
        req = urllib.request.Request(
            f"{JETLINKS_BASE}/authorize/login",
            data=json.dumps({"username": JETLINKS_USER, "password": JETLINKS_PASS}).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)["result"]["token"]
    except Exception as e:
        app.logger.warning("JetLinks 登录失败: %s", e)
        return None


def _jetlinks_query(path, payload):
    token = _jetlinks_token()
    if not token:
        return []
    try:
        req = urllib.request.Request(
            f"{JETLINKS_BASE}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Access-Token": token}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get("result", {}).get("data", [])
    except Exception as e:
        app.logger.warning("JetLinks 查询 %s 失败: %s", path, e)
        return []


@app.route("/api/platform/products", methods=["GET"])
def platform_products():
    products = _jetlinks_query("/device/product/_query", {"paging": False, "terms": []})
    return _resp(data=[{"id": p.get("id"), "name": p.get("name")} for p in products])


@app.route("/api/platform/devices", methods=["GET"])
def platform_devices():
    devices = _jetlinks_query("/device/instance/_query", {"paging": False, "terms": []})
    return _resp(data=[{
        "id": d.get("id"),
        "name": d.get("name"),
        "productId": d.get("productId"),
        "state": d.get("state", {}).get("value")
    } for d in devices])


# ---- 供 Python 终端读取的便捷函数 ----
def load_mapping() -> dict:
    """被 relay_terminal.py / modbus 采集终端 import 使用"""
    return _load()


if __name__ == "__main__":
    _mqtt_start()
    print(f"启动 Web 映射管理后台：http://localhost:5000")
    print(f"配置文件：{MAPPING_FILE}")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
