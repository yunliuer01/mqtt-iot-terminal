# MQTT 温湿度 / 继电器模拟终端 + Web 映射管理后台

基于 MQTT 的 IoT 模拟终端集合：把「温湿度」「继电器通道」这样的虚拟设备，通过
**EMQX → JetLinks** 接入物联网平台，实现属性上报、下行控制、功能回复的完整闭环。

仓库里同时带一个 **Web 映射管理后台**：把原先写死在代码里的
「继电器通道 ↔ 虚拟设备」「Modbus 传感器 ↔ 虚拟设备」映射关系，改成浏览器里可视化增删改。

---

## 目录结构

```
mqtt-iot-terminal/
├── config.py                    连接配置（MQTT / JetLinks / Modbus 默认值）
├── mqtt_base.py                 MQTT 上报基类（连接、重连、LWT、上报格式）
│
├── gui_sensor.py                ★ GUI 温湿度模拟器（拖滑块即上报）
├── start_gui.bat                双击启动 GUI
├── terminal_file.py             文件监听终端（改 JSON 文件触发上报）
├── terminal_modbus.py           Modbus 采集终端（轮询寄存器）
├── jetlinks_terminal.py         JetLinks 平台接入基类（双适配模式 + 下行控制）
│
├── relay_terminal.py            8 路继电器模拟终端（硬编码配置版）
├── relay_terminal_webcfg.py     ★ 继电器模拟终端（读 Web 映射配置版）
├── modbus_sim_server.py         本地 Modbus TCP 模拟从站（无实验平台时自测）
├── modbus_write.py              写入本组寄存器（演示用）
├── e2e_verify.py                温湿度链路端到端验证
├── relay_e2e_verify.py          继电器链路端到端验证
├── jetlinks_rule.sql            EMQX 规则转换 SQL（路线 A 用）
│
├── web/                         ★ Web 映射管理后台
│   ├── app.py                     Flask REST API
│   ├── mapping_loader.py          共享配置加载器（终端侧复用）
│   └── static/
│       ├── index.html             单页前端（Vue 3 + Element Plus + ECharts）
│       └── mapping.json           映射配置文件（真正的数据源）
│
├── diagnostics/                 一次性诊断/抓包/验证脚本（31 个，整理归位）
├── platform-setup/              平台资源创建与修复脚本（7 个，整理归位）
├── data/                        运行期数据（sensor_data.json 等）
└── archive/                     会话调试产物归档（不入库）
```

---

## 快速开始

```bash
pip install -r requirements.txt
```

### GUI 温湿度模拟器（推荐入门）

双击 `start_gui.bat`，或命令行：

```bash
python gui_sensor.py
```

拖动滑块调整温湿度，松手即自动上报 MQTT 并同步写入 `data/sensor_data.json`，
界面日志实时显示服务器回传消息。

| 终端 | 文件 | 数据来源 |
|------|------|----------|
| **GUI 模拟器** | `gui_sensor.py` | 图形界面拖滑块，松手即上报 |
| 文件监听终端 | `terminal_file.py` | 手动编辑本地 JSON，保存后立即上报 |
| Modbus 采集终端 | `terminal_modbus.py` | 轮询 Modbus TCP 寄存器，数值变化后上报 |

> GUI 模拟器与文件监听终端功能等价（内置上报，无需同时运行 `terminal_file.py`）。

---

## Web 映射管理后台

### 它解决什么问题

原来 `relay_terminal.py` 里 8 路继电器对应哪个虚拟设备、哪个物模型属性，是**写死在代码里**
的。改一个映射就得改代码、改完还得记住改了哪，多组协作时很容易对不上。

现在这些映射统一存在 `web/static/mapping.json`，用浏览器管理，终端启动时读取。

### 启动

```bash
python web/app.py
# 浏览器打开 http://localhost:5000
```

> 端口 5000，`debug=True`。已装依赖 `flask` / `flask-cors`（见 `requirements.txt`）。

### 界面功能

- **看板**：KPI 统计卡（继电器组数 / Modbus 传感器数 / 启用映射数 / 启用通道数）+
  ECharts 趋势与分布图
- **继电器通道**：新建 / 编辑 / 删除继电器组，逐通道配置「通道号 → 设备ID → 物模型属性 → 是否启用」
- **Modbus 传感器**：新建 / 编辑 / 删除传感器，配置从站 IP/端口、从站 ID、寄存器地址、
  上报周期、温湿度字段名
- **查看 JSON**：右上角按钮，直接看当前完整配置
- 改动先落到内存，底部会提示「有未保存的修改」，点保存才写盘

### REST API

统一响应格式：`{"ok": bool, "data": any, "msg": str}`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mapping` | 读取完整映射配置 |
| PUT | `/api/mapping` | **全量保存**（前端唯一使用的写入口） |
| PUT | `/api/mapping/relay/<group_id>` | 单条 upsert 继电器组（不存在则创建） |
| DELETE | `/api/mapping/relay/<group_id>` | 删除继电器组 |
| PUT | `/api/mapping/modbus/<sensor_id>` | 单条 upsert Modbus 传感器 |
| DELETE | `/api/mapping/modbus/<sensor_id>` | 删除 Modbus 传感器 |
| GET | `/api/platform/products` | 代理查询 JetLinks 产品列表 |
| GET | `/api/platform/devices` | 代理查询 JetLinks 设备列表 |

> 注意：**没有 POST 路由**。单条新建请用 `PUT /api/mapping/<kind>/<id>`（upsert 语义）。
> 前端走的是全量 `PUT /api/mapping`，不受影响。

### 配置文件结构（`web/static/mapping.json`）

```json
{
  "version": "1.0",
  "updated_at": "2026-09-11 10:09:26",
  "relay_groups":   [ { "id": "...", "name": "...", "channels": [ ... ] } ],
  "modbus_sensors": [ { "id": "...", "slave_ip": "192.168.20.59", "slave_port": 5502,
                        "slave_id": 1, "register_addr": "0x0005",
                        "report_interval": 5, "enabled": true } ]
}
```

### 终端读取映射配置

两个终端都新增了 `--mapping` / `--list` 参数。
**优先级：命令行参数 > mapping 配置 > 代码里的硬编码默认值**（只有你没显式传的参数才会被覆盖）。

```bash
# 继电器终端（Web 配置版）
python relay_terminal_webcfg.py --list                                    # 列出可用继电器组
python relay_terminal_webcfg.py --mapping web/static/mapping.json --group-id relay4_lfx

# Modbus 采集终端
python terminal_modbus.py --mapping web/static/mapping.json --list        # 列出可用传感器
python terminal_modbus.py --mapping web/static/mapping.json --sensor-id modbus-th-01
```

---

## MQTT 服务器与上报格式

配置在 `config.py`：`172.16.4.211:9783`，账号 `test` / `123456`。
命令行可用 `--host` / `--port` 临时覆盖。

- 数据主题：`terminal/{device_id}/th`，QoS 1
- 状态主题：`terminal/{device_id}/status`（遗嘱消息 online / offline，保留消息）

```json
{
  "device_id": "MODBUS-TERM-01",
  "type": "modbus",
  "temperature": 25.5,
  "humidity": 60.2,
  "timestamp": "2026-09-01T10:00:00"
}
```

### Modbus 采集终端

默认连接实验平台从站 **192.168.20.59:5502**，本组寄存器 **0x0005**。

寄存器编码约定（16 位）：**高 8 位 = 温度℃，低 8 位 = 湿度%RH**，
例如 `0x1F3D`（2597）解析为温度 31℃ / 湿度 61%RH。

```bash
python terminal_modbus.py                                              # 连实验平台
python modbus_sim_server.py                                            # 窗口1：本地模拟从站(5020)
python terminal_modbus.py --modbus-host 127.0.0.1 --modbus-port 5020   # 窗口2：本地自测
```

常用参数：`--reg 0x0005`、`--modbus-host` / `--modbus-port`、`--slave-id`、
`--interval 2`、`--deadband 1`。

写入寄存器演示：`python modbus_write.py --temp 26 --hum 58`

---

## JetLinks 平台接入

JetLinks 网页：`http://172.16.4.211:9000`（MQTT 接入端口仍为 9783）。

**平台账号（本小组）**

| 平台 | 账号 | 用途 |
|------|------|------|
| JetLinks 网页 | `admin5` / `Admin@group5` | 浏览器登录 9000，建产品/物模型/设备 |
| EMQX Dashboard | `group5` / `Admin@group5` | 管理端账号（18083 未开放，预留） |
| MQTT 设备接入 | `test` / `123456` | 终端连接 9783 用（实测有效，勿用 group5） |

### 两种适配路线

**路线 A（不改终端，EMQX 规则转换）**：终端保持原始报文 `terminal/{deviceId}/th`，
由 EMQX 规则引擎转换成 JetLinks 物模型格式并转发。规则 SQL 见 `jetlinks_rule.sql`。

```bash
python jetlinks_terminal.py --mode emqx
```

**路线 B（终端直接适配 JetLinks 报文）**：终端直接上报 `{"properties":{...}}`，
无需 EMQX 规则。

```bash
python jetlinks_terminal.py
```

### 平台下发控制

终端已订阅 JetLinks 下行主题，网页 **设备详情 → 功能调用** 点按钮即可控制：

| 平台操作 | 终端行为 |
|---|---|
| 功能调用 `setInterval(interval=3)` | 上报间隔改为 3 秒，回复 `{messageId, success, output}` |
| 读取属性 | 回复当前温湿度 `{messageId, properties, success}` |
| 修改属性 `temperature=30` | 写入本地 JSON 并回复，文件变化自动触发上报 |

> JetLinks 协议主题带前导斜杠（`/mqtt-iot/FILE-TERM-01/...`），与 `terminal/...` 格式不同。

---

## 八路继电器模拟终端

平台资源全部以 **`relay8_lfx` / `-lfx`** 命名，**未改动**任何温湿度/共享配置。

| 类型 | 资源 | 说明 |
|------|------|------|
| JetLinks 产品 | `relay8_lfx`（8路继电器-lfx） | 物模型 8 个属性 r1..r8（enum 1开/0关）+ 功能 `write` |
| JetLinks 设备 | `RELAY8-TERM-01` | 绑定上述产品 |
| EMQX 规则 | `rule_lfx_relay8_property` | 设备 `property/post` → `/properties/report` |
| EMQX 规则 | `rule_lfx_relay8_reply` | 设备 `function/post` → `/function/invoke/reply` |
| EMQX 规则 | `rule_lfx_relay8_cmd` | JetLinks `/function/invoke` → 设备 `/service/cmd`（纯透传） |

```bash
python relay_terminal.py --interval 5     # 硬编码配置版
python relay_e2e_verify.py                # 端到端：上线 + 上行 + 下行 write + 回复
```

状态只由平台下发的 `write` 命令改变，无随机翻转、无自动漂移（演示功能已按验收要求清理）。

> **踩坑记录**：本环境 EMQX 的 jq 子集仅支持对象构造类运算，`select` / `tonumber?` /
> `first()` / `//` 都会导致规则 `failed.exception`。因此命令规则采用 `SELECT payload`
> 纯透传，由模拟器在 Python 侧解析 JetLinks 原始报文。

---

## 辅助脚本

### `diagnostics/` — 一次性诊断与抓包

排查期写的探针，需要时按名字找：

| 脚本 | 用途 |
|------|------|
| `mqtt_monitor.py` | 订阅上报主题实时打印（`-t "terminal/#" -v`） |
| `invoke_probe.py` | 只看平台下发 `function/invoke` 的报文原文 |
| `downlink_probe.py` | 下行链路探针 |
| `test_invoke_sim.py` | 模拟平台下发 invoke，验证终端回复链路 |
| `fake_invoke_test.py` | 伪造下行报文，定位「幽灵回复者」 |
| `capture_flow.py` / `compare_flow.py` | 抓取并比对完整报文流 |
| `diag_*` / `probe_*` / `recv_*` / `verify_topics*` | 平台侧各项诊断 |

> 从仓库根目录或 `diagnostics/` 内部执行都可以（脚本已自动把仓库根目录加回 `sys.path`）。

### `platform-setup/` — 平台资源脚本

| 脚本 | 用途 |
|------|------|
| `relay_create_product.py` / `relay_create_device.py` / `relay_create_rules.py` | 创建继电器产品 / 设备 / EMQX 规则 |
| `relay_update_cmd_rule.py` | 升级命令透传规则 |
| `add_modbus_device.py` | 新增 Modbus 设备 |
| `rebind_gateway.py` | 重新绑定网关 |
| `jetlinks_platform_fix.py` | 平台侧修复 |

---

## 说明

- 所有终端均带 MQTT 自动重连、遗嘱消息（异常掉线时服务器代发 offline）
- 只在数值变化（超过 deadband）时上报，避免无意义刷屏；文件终端另有 5 秒兜底轮询
- Modbus 采集终端断线后自动重连
- `data/sensor_data.json` 是运行期状态，已从版本库移除（`.gitignore` 忽略）

## 目录整理说明

2026-09-11 做过一次整理：根目录此前混着 73 个文件（脚本、日志、平台快照），
现已把一次性诊断脚本归入 `diagnostics/`、平台脚本归入 `platform-setup/`、
会话产物归入 `archive/`，**根目录只保留核心链路 16 个文件**。

`archive/` 不进版本库，详见 `archive/README.md`。
