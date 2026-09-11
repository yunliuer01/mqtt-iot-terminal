# -*- coding: utf-8 -*-
"""一次性诊断脚本：只看 JetLinks 平台下发的 function/invoke 报文原文

用法:
    1. 先 STOP 所有 FILE-TERM-01 / MODBUS-TERM-01 终端进程（避免抢 clientId）
    2. python invoke_probe.py
    3. 切到 JetLinks UI -> 温湿度终端-lfx -> 设备功能 -> 设置温湿度 -> 点执行
    4. 脚本会打印接收到的原文 payload,完事后 Ctrl+C 退出

它不会写文件/写寄存器,只订阅读。

注意 clientId 必须 = 文件/Modbus 终端的 device_id(其中一个即可),
否则 JetLinks mqtt-client-gateway 不会把下行消息代理到本连接。
"""
import json
import logging
import sys

import paho.mqtt.client as mqtt

# --- 本脚本已从仓库根目录移入 diagnostics/，下面三行把仓库根目录加回 sys.path，
#     以便继续 `import config`（2026-09-11 目录整理时补）---
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("invoke-probe")

# 任选一个 device_id(精确等于 JetLinks 设备 ID),让平台下行能路由到这条连接
# 两个都订阅,看哪边先收到,就能确认平台到底把消息发到哪个主题
DEVICE_IDS = ["FILE-TERM-01", "MODBUS-TERM-01"]


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error("MQTT 连接失败 rc=%s", rc)
        sys.exit(1)
    log.info("已连接 MQTT %s:%d,作为 clientId=%s 上线",
             client._host, client._port, client._client_id.decode())
    subs = []
    for did in DEVICE_IDS:
        # 平台下行的三个相关主题全部订阅,把 ? 代替中文标签看 inputs 真实 key
        subs.extend([
            (f"/mqtt-iot/{did}/function/invoke", 1),
            (f"/mqtt-iot/{did}/function/invoke/reply", 1),
            (f"/mqtt-iot/{did}/properties/read", 1),
        ])
    client.subscribe(subs)
    log.info("已订阅以下主题(请到 UI 执行一次 \"设置温湿度\"):")
    for did in DEVICE_IDS:
        log.info("  /mqtt-iot/%s/function/invoke", did)
        log.info("  /mqtt-iot/%s/function/invoke/reply", did)
        log.info("  /mqtt-iot/%s/properties/read", did)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        dump = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        dump = msg.payload.decode("utf-8", errors="replace")
    print("\n" + "=" * 60)
    print("收到下行 ->", msg.topic)
    print(dump)
    print("=" * 60)


def main():
    # 用第一个 deviceId 作 clientId,精确匹配让平台能路由下行
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=DEVICE_IDS[0], clean_session=True,
    )
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, 60)
    client.loop_start()
    print(f"\n>>> 已就绪。现在去 UI 执行一次\"设置温湿度\",等待下行报文... <<<\n")
    try:
        while True:
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("退出")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
