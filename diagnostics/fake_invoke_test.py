# -*- coding: utf-8 -*-
"""假 invoke 实验：手动向 /mqtt-iot/FILE-TERM-01/function/invoke 发布一条伪造下行，
观察是否会出现非本终端的自动回复(unknown function)，从而定位"幽灵回复者"。"""
import json
import time
import uuid

import paho.mqtt.client as mqtt

# --- 本脚本已从仓库根目录移入 diagnostics/，下面三行把仓库根目录加回 sys.path，
#     以便继续 `import config`（2026-09-11 目录整理时补）---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import config

PRODUCT_ID = "mqtt-iot"
DEVICE_ID = "FILE-TERM-01"
received = []


def on_connect(client, userdata, flags, rc, properties=None):
    client.subscribe("/mqtt-iot/#", qos=1)
    print("[*] 已订阅 /mqtt-iot/#")


def on_message(client, userdata, msg):
    received.append((time.time(), msg.topic, msg.payload.decode("utf-8", "replace")))
    print(f"[recv] {msg.topic}\n       {msg.payload.decode('utf-8','replace')[:300]}")


def main():
    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"fake-invoke-{uuid.uuid4().hex[:6]}")
    c.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(config.MQTT_HOST, config.MQTT_PORT, 60)
    c.loop_start()
    time.sleep(1.5)

    # 伪造一条与平台格式一致的 invoke（随机 messageId）
    mid = f"fake-{uuid.uuid4().hex[:12]}"
    payload = {"headers": {"async": False},
               "messageId": mid,
               "deviceId": DEVICE_ID,
               "functionId": "setTH",
               "inputs": [{"name": "params", "value": {"temperature": 26, "humidity": 65}}]}
    topic = f"/{PRODUCT_ID}/{DEVICE_ID}/function/invoke"
    print(f"[pub] {topic} mid={mid}")
    c.publish(topic, json.dumps(payload), qos=1)

    time.sleep(6)
    print("\n=== 6s 内收到的所有消息 ===")
    if not received:
        print("(无任何消息)")
    # 只看非周期上报的消息
    for ts, t, p in received:
        if "/properties/report" in t or "/online" in t or "/th" in t:
            continue
        print(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {t}\n    {p[:300]}")
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
