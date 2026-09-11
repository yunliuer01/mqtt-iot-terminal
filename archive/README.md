# archive/ — 会话调试产物归档

本目录**不进版本库**（见根目录 `.gitignore`），只在本机保留，供事后追溯。

## 为什么会有这个目录

2026-09-11 做了一次项目整理。此前仓库根目录混着脚本、运行日志、平台账号快照，
一共 73 个文件，看不出哪些是「真正要跑的东西」。整理原则是**归档而不是删除**——
这些文件记录了 JetLinks 接入、下行链路排查的全过程，将来复盘还要翻。

整理后的根目录只保留核心链路：

| | 整理前 | 整理后 |
|---|---|---|
| 根目录文件 | 73 个 | 16 个 |
| 新增目录 | — | `diagnostics/`（一次性诊断）、`platform-setup/`（平台资源脚本）、`archive/` |

## 目录结构

```
archive/session-debug-2026-09/
├── platform-snapshots/   EMQX 客户端列表、产品/设备备份、JetLinks 前端 bundle 等平台侧快照
├── logs/                 进程命令行快照、Modbus 从站运行日志
└── scripts/              jetlinks_terminal_setTH_bak.py（已被正式版取代的旧备份）
```

## 里面有什么值得留意的

- **`platform-snapshots/_product_backup.json` / `_ref_relay4mt_device*.json`** —
  平台侧的原始产品/设备定义。物模型对不上时，拿这些跟当前平台状态比。
- **`platform-snapshots/_network_configs.json` / `_g5_network_backup.json`** —
  网络配置备份，含连接信息，所以没入库。

## 怎么找回文件

归档用的是 `mv`，没有再压缩。直接用 `archive/session-debug-2026-09/<类别>/` 路径打开即可。
确定用不上时，删掉整个 `archive/` 目录不影响任何构建或运行。
