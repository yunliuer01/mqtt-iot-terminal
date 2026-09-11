# -*- coding: utf-8 -*-
"""继电器模拟终端（Web 配置版）

从 web/static/mapping.json 读取继电器组映射，不再把产品/设备/属性写死在代码里。

用法：
    # 先启动 Web 管理后台并配置好映射
    python web/app.py

    # 再运行本终端（默认使用 mapping.json 中第一个继电器组）
    python relay_terminal_webcfg.py

    # 指定使用某个组
    python relay_terminal_webcfg.py --group-id relay8_lfx

    # 指定映射文件路径
    python relay_terminal_webcfg.py --mapping web/static/mapping.json --group-id relay4_lfx
"""
import argparse
import json
import logging
import sys
import threading
import time

import paho.mqtt.client as mqtt

# 把项目根目录加入路径，方便 import web.mapping_loader
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from web.mapping_loader import load_mapping, get_relay_group

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("relay-terminal-webcfg")


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


class ChannelModel:
    """根据 Web 配置动态生成通道状态表"""

    def __init__(self, channels_cfg):
        # channels_cfg: [{"ch":1, "attr":"r1", "name":"开关1", "enabled":True}, ...]
        self.channels = []
        for c in sorted(channels_cfg, key=lambda x: x.get("ch", 0)):
            if c.get("enabled", True):
                self.channels.append({
                    "ch": int(c["ch"]),
                    "attr": str(c["attr"]),
                    "name": str(c.get("name", "")),
                    "state": False
                })
        self.lock = threading.Lock()

    def set_all(self, writes):
        """writes: {attr: value, ...}，返回实际变化的 ch 列表"""
        changed = []
        with self.lock:
            for ch in self.channels:
                attr = ch["attr"]
                if attr in writes:
                    val = _to_bool(writes[attr])
                    if ch["state"] != val:
                        ch["state"] = val
                        changed.append(ch["ch"])
            states = {c["attr"]: c["state"] for c in self.channels}
        return changed, states

    def snapshot(self):
        with self.lock:
            return {c["attr"]: c["state"] for c in self.channels}


class RelaySimulatorWebcfg:
    def __init__(self, group_cfg, host=None, port=None, username=None, password=None):
        self.cfg = group_cfg
        self.product_id = group_cfg["product_id"]
        self.device_id = group_cfg["device_id"]
        self.broker = group_cfg.get("broker", {})
        self.command = group_cfg.get("command", {})
        self.model = ChannelModel(group_cfg.get("channels", []))

        self.host = host or self.broker.get("host", "172.16.4.211")
        self.port = port or self.broker.get("port", 9783)
        self.username = username or self.broker.get("username", "test")
        self.password = password or self.broker.get("password", "123456")
        self.interval = group_cfg.get("report_interval", 5.0)

        self.topic_property = f"/{self.product_id}/{self.device_id}/property/post"
        self.topic_reply = f"/{self.product_id}/{self.device_id}/function/post"
        self.topic_cmd = self.command.get("topic_template",
                                          "/{product_id}/{device_id}/service/cmd") \
            .format(product_id=self.product_id, device_id=self.device_id)

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.device_id, clean_session=True, protocol=mqtt.MQTTv311)
        self.client.username_pw_set(self.username, self.password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.will_set(f"/{self.product_id}/{self.device_id}/offline",
                             json.dumps({"deviceId": self.device_id}), qos=1)
        self._stop = threading.Event()

    # ---------- MQTT 回调 ----------
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("已连接 MQTT %s:%d, 订阅命令 %s", self.host, self.port, self.topic_cmd)
            client.subscribe(self.topic_cmd, qos=1)
            self.publish_property()
        else:
            log.error("连接失败 rc=%s", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        if rc != 0 and not self._stop.is_set():
            log.warning("连接断开 rc=%s, 等待自动重连", rc)

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            log.error("命令报文解析失败: %s body=%s", e, msg.payload[:200])
            return
        log.info("收到平台下行命令: %s", json.dumps(data, ensure_ascii=False))
        self.handle_command(data)

    # ---------- 业务 ----------
    def _extract_command(self, data):
        cmd_id = data.get("messageId") or data.get("id") or ""
        method = data.get("functionId") or data.get("method") or ""
        writes = {}
        inputs = data.get("inputs")
        if isinstance(inputs, list):
            for item in inputs:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", ""))
                val = item.get("value")
                if name == "params" and isinstance(val, dict):
                    writes.update(val)
                elif name:
                    writes[name] = val
        params = data.get("params")
        if isinstance(params, dict):
            writes.update(params)
        return cmd_id, method, writes

    def handle_command(self, data):
        cmd_id, method, writes = self._extract_command(data)
        expected_method = self.command.get("method", "write")
        if not method:
            log.warning("命令缺少 method/functionId: %s",
                        json.dumps(data, ensure_ascii=False)[:200])
            return
        if method != expected_method:
            log.warning("未知方法 %s（期望 %s）", method, expected_method)
            self.publish_reply(cmd_id, method, False, f"未知功能: {method}")
            return

        # 把 writes 里的 rN / chN_state 转换为 attr
        attr_writes = {}
        for k, v in writes.items():
            if k.startswith("r") and k[1:].isdigit():
                attr_writes[k] = v
            elif k.startswith("ch") and k.endswith("_state"):
                try:
                    ch = int(k[2:-6])
                    attr = None
                    for c in self.model.channels:
                        if c["ch"] == ch:
                            attr = c["attr"]
                            break
                    if attr:
                        attr_writes[attr] = v
                except ValueError:
                    pass

        changed, states = self.model.set_all(attr_writes)
        if changed:
            log.info("写继电器执行: 通道%s 已切换 -> %s",
                     changed, self.state_desc(states))
        else:
            log.info("写继电器执行: 状态无变化 -> %s", self.state_desc(states))
        self.publish_property()
        self.publish_reply(cmd_id, expected_method, True,
                           f"OK 已写入: {self.state_desc(states)}")

    def publish_property(self):
        snap = self.model.snapshot()
        payload = {"deviceId": self.device_id, "timestamp": int(time.time() * 1000)}
        payload.update(snap)
        body = json.dumps(payload, ensure_ascii=False)
        self.client.publish(self.topic_property, body, qos=1)
        log.info("属性上报 -> %s: %s", self.topic_property,
                 json.dumps({k: v for k, v in payload.items()
                             if k not in ("timestamp", "deviceId")}, ensure_ascii=False))

    def publish_reply(self, cmd_id, method, success, message):
        payload = {"deviceId": self.device_id, "id": cmd_id,
                   "success": bool(success), "method": method, "message": message}
        body = json.dumps(payload, ensure_ascii=False)
        self.client.publish(self.topic_reply, body, qos=1)
        log.info("命令响应 -> %s: %s", self.topic_reply,
                 json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def state_desc(states):
        return " ".join(f"{k}={1 if v else 0}" for k, v in sorted(states.items()))

    # ---------- 主循环 ----------
    def _auto_loop(self):
        last_report = time.time()
        while not self._stop.wait(0.5):
            now = time.time()
            if now - last_report >= self.interval:
                last_report = now
                if self.client.is_connected():
                    self.publish_property()

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()
        threading.Thread(target=self._auto_loop, daemon=True).start()
        log.info("继电器模拟终端已启动（Web 配置） 设备=%s 产品=%s broker=%s:%d 周期=%ss",
                 self.device_id, self.product_id, self.host, self.port, self.interval)
        log.info("映射通道：%s", ", ".join(f"ch{c['ch']}->{c['attr']}"
                                          for c in self.model.channels))

    def stop(self):
        self._stop.set()
        self.client.loop_stop()
        self.client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="继电器模拟终端（Web 配置版）")
    parser.add_argument("--mapping", default="web/static/mapping.json", help="映射文件路径")
    parser.add_argument("--group-id", default=None, help="使用哪个继电器组（默认第一个）")
    parser.add_argument("--list", action="store_true", help="列出可用的继电器组并退出")
    args = parser.parse_args()

    cfg = load_mapping(args.mapping)
    if args.list:
        print("可用的继电器组：")
        for g in cfg.get("relay_groups", []):
            print(f"  {g['id']:20s} {g['name']:30s} device={g['device_id']} product={g['product_id']}")
        return

    groups = cfg.get("relay_groups", [])
    if not groups:
        print("错误：mapping.json 中没有继电器组配置，请先通过 Web 界面创建。", file=sys.stderr)
        sys.exit(1)

    group = None
    if args.group_id:
        group = get_relay_group(args.group_id, args.mapping)
        if not group:
            print(f"错误：找不到继电器组 {args.group_id}", file=sys.stderr)
            sys.exit(1)
    else:
        group = groups[0]

    sim = RelaySimulatorWebcfg(group)
    try:
        sim.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止...")
        sim.stop()


if __name__ == "__main__":
    main()
