# 迭代十七严格离线网络验收记录（2026-09-24）

## 范围与结论

本轮验证 PRD-OFF-002 与 F12，不接入 OCR、真实文本模型或其他外部 API。统一模型网关的严格离线门禁已使用合成服务商、合成密钥和 TEST-NET 保留地址执行 10 次负向验证，10 次均在服务商和模型路由前返回 `OFFLINE_MODE_BLOCKED`。

当前 Codex 会话不是 Windows 管理员，无法启动 PktMon 驱动；直接启动服务返回 `OpenService FAILED 5: Access is denied.`。因此网络层抓包没有执行，PRD-OFF-002 和 F12 仍判定为“部分实现/部分通过”，不得登记为通过。

机器可读原始结果保存在 [`evidence/offline-network-2026-09-24/current-device.json`](evidence/offline-network-2026-09-24/current-device.json)。其中 UTC 时间为 2026-09-25，与本机 America/Los_Angeles 的 2026-09-24 属于同一次执行。

## 验证设计

- `scripts/measure_strict_offline_gateway.py` 在独立临时数据库中创建 synthetic 项目、外部服务商和文本模型档案。
- 目标使用 IANA TEST-NET-1 保留地址 `192.0.2.1:9`，不使用 DNS，也不指向真实供应商。
- 网络探针配置一个合成 DPAPI 密钥，使离线门禁一旦回归，调用具备继续到连接阶段的条件；该密钥不是真实凭据。
- 每次调用必须在路由前阻断，调用记录不得保存服务商或模型档案 ID，提示词和合成密钥明文不得出现在 SQLite 文件中。
- `scripts/measure_offline_network_acceptance.ps1` 使用同一 IP、端口、TCP SYN 过滤条件运行两段 PktMon 捕获。
- 第一段通过直接套接字连接生成正向对照；只有捕获包数大于 0，才证明抓包装置和过滤条件有效。
- 第二段执行 10 次严格离线网关调用；通过条件为应用层全部阻断且目标数据包数等于 0。
- PCAPNG 由仓库脚本独立解析块结构并统计数据包块，结果同时记录两个 PCAPNG 文件的 SHA-256。

## 当前设备结果

| 项目 | 结果 | 判定 |
| --- | --- | --- |
| 环境 | Windows 11 Enterprise 10.0.22631，64 位 | 已记录 |
| 管理员权限 | 否 | 环境受阻 |
| PktMon | 已安装；驱动状态 `Stopped` | 已记录 |
| 合成网络探针 | 已武装；目标 `192.0.2.1:9` | 已记录 |
| 应用层调用 | 10 次，10 次 `OFFLINE_MODE_BLOCKED` | 通过 |
| 阻断位置 | 10 条调用记录均无服务商和模型档案 ID | 通过 |
| 明文检查 | 提示词和合成密钥均未出现在注册库文件 | 通过 |
| 正向对照抓包 | 未执行 | 环境受阻 |
| 严格离线抓包 | 未执行 | 环境受阻 |
| F12 总判定 | 部分通过 | 未闭合 |

## 受控管理员会话复测

操作员必须先确认设备没有其他 PktMon 会话和过滤器，因为脚本会清除全部 PktMon 过滤器。随后在仓库根目录的管理员 PowerShell 中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/measure_offline_network_acceptance.ps1 `
  -Output .runtime/offline-network/result.json `
  -ConfirmNoExistingPktmonSession `
  -ConfirmNoExistingPktmonFilters
```

只有结果同时满足以下条件才可关闭 F12：

1. `application_layer.passed=true`；
2. `packet_capture.positive_control.packet_blocks>0`；
3. `packet_capture.strict_offline.packet_blocks=0`；
4. 顶层 `status=passed` 且 `passed=true`。

如任一条件不满足，保留 `.runtime/offline-network-*` 下的 ETL、PCAPNG 和 JSON 原件，不得改写为通过。PCAPNG 可能包含本机网络元数据，只能保存在访问受控的验收目录，不提交仓库。

命令参数依据 Microsoft Learn 的 [`pktmon start`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/pktmon-start)、[`pktmon filter add`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/pktmon-filter-add) 和 [`pktmon etl2pcap`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/pktmon-etl2pcap) 文档；过滤器同时匹配目标 IP、端口和 TCP SYN。

## 自动化覆盖

`backend/tests/test_offline_network_acceptance.py` 覆盖：

- 严格离线调用在路由前阻断，提示词和合成密钥明文不落库；
- PCAPNG section、interface 和 enhanced packet block 的计数；
- 截断或长度不合法的 PCAPNG 拒绝。

## 完整质量门禁

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1`：通过。
  - 前端 ESLint：通过。
  - 前端 Vitest：37 项通过。
  - 前端生产构建：通过。
  - Python Ruff：通过。
  - 许可证归档：41 个文件逐字节校验通过。
  - Pytest：118 项通过。
- `npm.cmd --prefix frontend run e2e`：10 项通过，8 项按既定设备条件跳过。

OCR 与真实外部 API 仍按既定顺序放在最后。
