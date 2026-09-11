# -*- coding: utf-8 -*-
"""setTH 链路全抓包 v3：订阅 /mqtt-iot/# 捕获每条原始消息（完整 payload），
逐个触发 FILE-TERM-01 / MODBUS-TERM-01 的 setTH，对照 REST 返回，
重点看 reply topic 上到底有几条回复、各自 messageId 与 invoke 是否一致。"""
import json
import threading
import time
import urllib.request
import urllib.error

import paho.mqtt.client as mqtt

JL = "http://172.16.4.211:9000/api"
EMQX = "http://172.16.4.211:9183/api/v5"
HOST = "172.16.4.211"
PORT = 9783

msgs = []
lock = threading.Lock()


def jl_req(method, path, data=None, token=None, raw=False):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(JL + path, data=body,
                               headers={"Content-Type": "application/json"})
    r.get_method = lambda: method
    if token:
        r.add_header("X-Access-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            content = x.read().decode("utf-8", "replace")
            return content if raw else json.loads(content)
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_msg": e.read(500).decode("utf-8", "replace")}


def main():
    tok = jl_req("POST", "/authorize/login",
                 {"username": "admin5", "password": "Admin@group5"})
    token = tok.get("result", {}).get("token")
    if not token:
        print("[FAIL] JetLinks 登录失败:", json.dumps(tok, ensure_ascii=False)[:300])
        return
    print("[OK] JetLinks 登录成功")

    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id="setth-diag-v3")
    c.username_pw_set("test", "123456")

    def on_msg(cl, ud, m):
        with lock:
            msgs.append((time.time(), m.topic, m.payload.decode("utf-8", "replace")))

    c.on_message = on_msg
    c.connect(HOST, PORT, 60)
    c.loop_start()
    c.subscribe("/mqtt-iot/#", qos=1)
    time.sleep(1.2)

    for did in ["FILE-TERM-01", "MODBUS-TERM-01"]:
        with lock:
            msgs.clear()
        t0 = time.time()
        print(f"\n{'='*70}\n>>> [{time.strftime('%H:%M:%S')}] 触发 {did} setTH(26,65)")
        resp = jl_req("POST", f"/device/instance/{did}/function/setTH",
                      {"params": {"temperature": 26, "humidity": 65}}, token=token)
        dt = time.time() - t0
        print(f"    REST 返回({dt:.1f}s): {json.dumps(resp, ensure_ascii=False)[:500]}")
        print(f"    --- 等待 8s 观察 MQTT 消息 ---")
        time.sleep(8)
        with lock:
            snapshot = list(msgs)
        if not snapshot:
            print("    (8s 内未捕获到任何 /mqtt-iot/# 消息)")
        for ts, t, p in snapshot:
            # 滤掉周期性 properties/report（占日志）
            if "/properties/report" in t and "function" not in t:
                continue
            print(f"    [{time.strftime('%H:%M:%S', time.localtime(ts))}] {t}")
            try:
                obj = json.loads(p)
                print("        " + json.dumps(obj, ensure_ascii=False))
            except Exception:
                print("        " + p[:500])
        with lock:
            msgs.clear()

    c.loop_stop()
    c.disconnect()
    print("\n[done]")


if __name__ == "__main__":
    main()
