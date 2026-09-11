# -*- coding: utf-8 -*-
"""列出 EMQX 上所有订阅 /mqtt-iot 相关 function/invoke 主题的客户端（找出"幽灵回复者"）"""
import json
import urllib.request
import urllib.parse

EMQX = "http://172.16.4.211:9183/api/v5"


def login():
    r = urllib.request.Request(EMQX + "/login",
                               data=json.dumps({"username": "group5", "password": "Admin@group5"}).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=15) as x:
        return json.loads(x.read().decode())["token"]


def emqx_get(path, token):
    r = urllib.request.Request(EMQX + path,
                               headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(r, timeout=10) as x:
            return json.loads(x.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_msg": e.read(300).decode("utf-8", "replace")}


def main():
    tok = login()
    # 全量订阅表，找 function/invoke / function/invoke/reply 的订阅者
    subs = emqx_get("/subscriptions?limit=200", tok)
    rows = subs.get("data", []) if isinstance(subs, dict) else []
    print(f"EMQX 订阅总数: {len(rows)}\n")
    print("=== 含 function/invoke 或 mqtt-iot 的订阅 ===")
    for s in rows:
        topic = s.get("topic", "")
        if "function/invoke" in topic or "mqtt-iot" in topic:
            print(f"  clientid={s.get('clientid')!r:40} qos={s.get('qos')} topic={topic!r}  node={s.get('node','')}")
    print("\n=== 全部订阅者 clientid 去重（看有哪些客户端在订阅）===")
    seen = set()
    for s in rows:
        cid = s.get("clientid", "")
        if cid not in seen:
            seen.add(cid)
            print(f"  {cid!r}")


if __name__ == "__main__":
    main()
