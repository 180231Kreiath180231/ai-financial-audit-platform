# 迭代十六离线备份恢复与许可证归档验收记录（2026-09-24）

## 范围

本轮完成不依赖安装器、OCR 或外部 API 的本地完整备份、校验、隔离恢复，以及 Windows x86_64 生产依赖许可证归档。备份演练只使用合成项目，不读取、复制或覆盖日常项目数据。安装、程序升级和卸载仍需先确定 Windows 安装器与数据保留策略。

## 实现与安全边界

- `scripts/manage_local_backup.py` 提供 `backup`、`verify`、`restore` 三个命令。
- 备份收集注册库、DPAPI 密文和全部注册项目；应用数据目录内项目不会在应用区重复保存。
- SQLite 使用 Backup API 快照；清单逐文件保存字节数和 SHA-256，验证同时执行数据库 `integrity_check`。
- 应用未停止确认、现有目标目录、路径穿越、符号链接、重叠项目目录和源目录内输出均被拒绝。
- 恢复只写入新目录，并将项目路径改写到隔离项目根目录，不修改源注册库和源项目。
- 备份目录包含完整敏感数据且没有新增整体加密；必须存放在受控位置。DPAPI 密文跨 Windows 用户或设备不可直接解密。
- SHA-256 清单可发现清单保留后的文件变化，但清单未签名，不能对抗同时具有备份写权限的攻击者。

## Windows 合成实机演练

原始机器可读结果保存在 [`evidence/backup-restore-2026-09-24/synthetic-drill.json`](evidence/backup-restore-2026-09-24/synthetic-drill.json)。

| 项目 | 结果 | 结论 |
| --- | --- | --- |
| 环境 | Windows 11 10.0.22631；Python 3.12.13；16 逻辑处理器；33,854,259,200 字节物理内存 | 已记录 |
| 数据范围 | 2 个合成项目：1 个在应用数据目录内，1 个在目录外 | 通过 |
| 备份 | 6 个文件，881,034 字节，0.0853 秒 | 通过 |
| 独立校验 | 文件清单、SHA-256、3 个 SQLite 数据库完整性，0.0263 秒 | 通过 |
| 隔离恢复 | 2 个项目，0.0694 秒 | 通过 |
| 数据一致性 | 两类文件内容、项目审计事件数量、严格离线状态均保留 | 通过 |
| 路径安全 | 恢复后的项目路径全部改写到新项目根目录，源路径不变 | 通过 |
| 密钥边界 | 合成 Token 经真实 Windows DPAPI 加密，恢复后由同一用户成功解密 | 通过 |
| 外部访问 | 0 次 | 通过 |

演练命令：

```powershell
uv run python scripts/measure_backup_restore_acceptance.py --output docs/acceptance/evidence/backup-restore-2026-09-24/synthetic-drill.json
```

## 自动化

`backend/tests/test_local_backup.py` 覆盖：

- 应用目录内与目录外项目的完整备份和恢复；
- 密钥密文、普通文件、SQLite 数据和设置保留；
- 清单保留前提下的 SHA-256 文件变化检测；
- 应用停止显式确认；
- 恢复目标禁止覆盖；
- 恶意清单路径拒绝。

## 生产依赖许可证归档

- `scripts/archive_production_licenses.py` 从已安装生产依赖、`uv.lock` 和 `frontend/package-lock.json` 生成确定性归档。
- [`../licenses/production/manifest.json`](../licenses/production/manifest.json) 记录 33 个 Python 生产包、7 个当前 Windows 安装的 npm 生产包、锁文件摘要、逐包版本、许可证声明、原始文本路径和归档 SHA-256。
- 共归档 40 份逐包合并许可证文本；pypdfium2 的 Windows x64 PDFium 构建许可证和 pdfjs-dist 内嵌资源许可证一并收集。
- npm 锁文件中 10 个其他平台 `@napi-rs/canvas` 可选包未安装在本机，清单单列其版本和 MIT 声明；当前 Windows x64 包使用上游共享 MIT 文本。
- 质量门禁会在当前锁定环境中重建临时归档并逐字节比较 41 个文件，防止依赖升级后清单静默过期。
- 当前归档未发现 GPL/AGPL 声明，但技术归档不等于法务批准；MPL-2.0、MIT-CMU、PDFium 组合许可证和通知义务仍需发布负责人复核。

## 完整质量门禁

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1`：通过。
  - 前端 ESLint：通过。
  - 前端 Vitest：37 项通过。
  - 前端生产构建：通过。
  - Python Ruff：通过。
  - 许可证归档：41 个文件逐字节校验通过。
  - Pytest：115 项通过。
- `npm.cmd --prefix frontend run e2e`：10 项通过，8 项按既定设备条件跳过。

## 结论与剩余边界

本地数据备份、独立校验、隔离恢复和当前 Windows 生产依赖许可证归档已形成可复核闭环，但不能据此宣称整个发布安装演练或法务复核完成。以下项目仍未执行：

- Windows 安装器首次安装；
- 从旧版本程序升级并验证数据库自动迁移；
- 程序卸载，以及“保留数据/删除数据”的产品行为；
- 跨 Windows 用户或跨设备的密钥迁移；
- 真实客户数据恢复。

这些事项不能在未确定安装器和数据保留策略时自行实现。OCR 与外部模型 API 仍按用户指定顺序放在最后。
