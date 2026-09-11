# -*- coding: utf-8 -*-
"""查 JetLinks 平台：产品 mqtt-iot 的物模型/功能定义 + 设备接入网关配置"""
import json
import urllib.request
import urllib.error

JL = "http://172.16.4.211:9000/api"


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
        return {"_http": e.code, "_msg": e.read(400).decode("utf-8", "replace")}


def walk(obj, depth=0):
    """打印 JSON 的关键结构"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print("  " * depth + f"{k}:")
                walk(v, depth + 1)
            else:
                s = str(v)
                print("  " * depth + f"{k} = {s[:120]}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:10]):
            print("  " * depth + f"[{i}]")
            walk(item, depth + 1)


def main():
    tok = jl_req("POST", "/authorize/login",
                 {"username": "admin5", "password": "Admin@group5"})["result"]["token"]

    print("========== 产品 mqtt-iot 详情 ==========")
    prod = jl_req("GET", "/product/mqtt-iot", token=tok)
    if isinstance(prod, dict) and prod.get("result"):
        p = prod["result"]
        for k in ["id", "name", "messageProtocol", "transportProtocol", "deviceType"]:
            print(f"  {k} = {p.get(k)}")
        conf = p.get("configuration") or {}
        if isinstance(conf, str):
            try:
                conf = json.loads(conf)
            except Exception:
                pass
        print("  configuration =", json.dumps(conf, ensure_ascii=False)[:1500])
        # 物模型
        meta = p.get("metadata") or p.get("model") or {}
        print("  metadata keys:", list(meta.keys()) if isinstance(meta, dict) else type(meta))
        if isinstance(meta, dict):
            for mk in ["functions", "properties", "events"]:
                if mk in meta:
                    print(f"  --- metadata.{mk} ---")
                    walk(meta[mk], depth=1)
    else:
        print(json.dumps(prod, ensure_ascii=False)[:600])

    print("\n========== 设备 FILE-TERM-01 详情 ==========")
    dev = jl_req("GET", "/device/instance/FILE-TERM-01", token=tok)
    if isinstance(dev, dict) and dev.get("result"):
        d = dev["result"]
        for k in ["id", "name", "productId", "state", "online", "registryTime",
                  "lastMetadataTime", "deviceType", "parentId"]:
            print(f"  {k} = {d.get(k)}")
        conf = d.get("configuration") or {}
        if isinstance(conf, str):
            try:
                conf = json.loads(conf)
            except Exception:
                pass
        print("  configuration =", json.dumps(conf, ensure_ascii=False)[:800])
        # 物模型（设备级可覆盖）
        meta = d.get("metadata") or {}
        if isinstance(meta, dict) and ("functions" in meta or "properties" in meta):
            print("  --- device metadata ---")
            walk(meta, depth=1)
    else:
        print(json.dumps(dev, ensure_ascii=False)[:600])

    print("\n========== 设备 MODBUS-TERM-01 详情 ==========")
    dev2 = jl_req("GET", "/device/instance/MODBUS-TERM-01", token=tok)
    if isinstance(dev2, dict) and dev2.get("result"):
        d = dev2["result"]
        for k in ["id", "name", "productId", "state", "online", "deviceType"]:
            print(f"  {k} = {d.get(k)}")
        conf = d.get("configuration") or {}
        if isinstance(conf, str):
            try:
                conf = json.loads(conf)
            except Exception:
                pass
        print("  configuration =", json.dumps(conf, ensure_ascii=False)[:800])
    else:
        print(json.dumps(dev2, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
