# -*- coding: utf-8 -*-
"""自动诊断 setTH 下行链路（只读 + 触发一次功能调用，不改任何配置）"""
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
        with urllib.request.urlopen(r, timeout=25) as x:
            content = x.read().decode("utf-8", "replace")
            return content if raw else json.loads(content)
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_msg": e.read(300).decode("utf-8", "replace")}


def emqx_get(path, token):
    r = urllib.request.Request(EMQX + path,
                               headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(r, timeout=10) as x:
            return json.loads(x.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_msg": e.read(300).decode("utf-8", "replace")}


def main():
    # 1. 登录 JetLinks
    tok = jl_req("POST", "/authorize/login",
                 {"username": "admin5", "password": "Admin@group5"})
    token = tok.get("result", {}).get("token")
    if not token:
        print("[FAIL] JetLinks 登录失败:", json.dumps(tok, ensure_ascii=False)[:300])
        return
    print("[OK] JetLinks 登录成功")

    # 2. 登录 EMQX Dashboard API
    dash = json.load(urllib.request.urlopen(
        urllib.request.Request(EMQX + "/login",
                               data=json.dumps(
                                   {"username": "group5", "password": "Admin@group5"}).encode(),
                               headers={"Content-Type": "application/json"}),
        timeout=15))
    dash_tok = dash.get("token")
    print("[OK] EMQX 登录成功")

    # 3. 查 EMQX 上 mqtt-iot 网关与终端客户端在线情况
    print("\n=== EMQX 在线客户端 (按 clientid 过滤 mqtt-iot/TERM) ===")
    for cid in ["FILE-TERM-01", "MODBUS-TERM-01"]:
        d = emqx_get(f"/clients?clientid={cid}", dash_tok)
        clients = d.get("data", []) if isinstance(d, dict) else []
        if clients:
            for c in clients:
                print(f"   {cid}: 在线 connected={c.get('connected')} ip={c.get('ip_address')}")
        else:
            print(f"   {cid}: 【不在线】")

    # 4. 订阅 MQTT 下行主题
    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id="setth-diag")
    c.username_pw_set("test", "123456")

    def on_msg(cl, ud, m):
        with lock:
            msgs.append((time.time(), m.topic, m.payload.decode("utf-8", "replace")))

    c.on_message = on_msg
    c.connect(HOST, PORT, 60)
    c.loop_start()
    c.subscribe("/mqtt-iot/#", qos=1)
    time.sleep(1)
    print("\n[OK] 已订阅 /mqtt-iot/#，准备触发 setTH")

    # 5. 触发 JetLinks 平台功能调用
    for did in ["FILE-TERM-01", "MODBUS-TERM-01"]:
        print(f"\n>>> 触发平台功能调用: {did} setTH(temp=26, hum=65)")
        resp = jl_req("POST", f"/device/instance/{did}/function/setTH",
                      {"params": {"temperature": 26, "humidity": 65}}, token=token)
        print(f"   REST 响应: {json.dumps(resp, ensure_ascii=False)[:400]}")

    print("\n>> 监听 12s 内 MQTT 消息 ...")
    time.sleep(12)
    with lock:
        snapshot = list(msgs)
    if not snapshot:
        print("   (12s 内未捕获到任何 /mqtt-iot/# 消息)")
    for ts, t, p in snapshot:
        print(f"   [{time.strftime('%H:%M:%S', time.localtime(ts))}] {t}")
        print(f"       {p[:400]}")
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
