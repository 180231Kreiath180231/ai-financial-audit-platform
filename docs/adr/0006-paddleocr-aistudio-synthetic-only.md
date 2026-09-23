# ADR-0006：PaddleOCR AI Studio 合成数据专用接入

- 状态：已接受
- 日期：2026-09-22
- 关联：PRD-DOC-003、PRD-MDL-001 至 005、PRD-OFF-001、F05、F07、F12

## 背景

用户指定 PaddleOCR AI Studio 异步 Jobs API 与 `PaddleOCR-VL-1.6`。供应商示例支持本地文件上传、状态轮询和 JSONL 结果下载，但未提供远端文件删除接口或可验证的保留期限。根据最小外发和远端生命周期要求，不能据此批准真实审计资料上传。

## 决策

- 新增隔离的 `paddleocr_aistudio` 服务商类型，不把异步 Job 协议伪装成 OpenAI-compatible 接口。
- Jobs Endpoint 固定为用户批准的 `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`，模型固定为当前批准的 `PaddleOCR-VL-1.6`，能力必须且只能声明 `vision` 与 `file_upload`。
- Access Token 使用现有 Windows 当前用户 DPAPI 存储；数据库、日志、测试快照和 API 响应不保存或回显明文。
- 真实调用必须同时满足：synthetic 项目、关闭严格离线、项目显式外发授权、启用的 PaddleOCR 服务商和模型档案、已配置密钥。非 synthetic 项目在网关内再次硬阻断。
- 只把当前扫描页渲染为临时 PNG 后上传，不上传整份 PDF，不发送原文件名；完成、失败、中断后立即关闭位图并删除本地临时文件。
- 只读取 JSONL 中 `layoutParsingResults[].markdown.text`；不请求或下载 `markdown.images`、`outputImages`。
- Job 状态只接受 `pending`、`running`、`done`、`failed`；请求具有超时、有限重试、十分钟 Job 等待上限、16 MB 响应上限和本地任务安全点中断。
- JSONL 结果地址必须使用 HTTPS，并在连接前拒绝私网、回环、链路本地、保留和不可解析地址；所有 HTTP 重定向均拒绝。
- 调用审计保存项目、任务、服务商、实际模型、页码、图像 SHA-256、请求摘要、Job ID、重试、耗时、结果和 `remote_cleanup_status=unsupported`。不保存原文件名、页面图片或令牌。

## 后果

该接入可以用合成扫描页验证真实网络协议、DPAPI 密钥、外发门禁、页级证据和错误恢复，但不代表真实审计资料已获准外发，也不完成 F07 的真实数据验收。只有取得服务商保留期限、删除能力和数据处理条款并完成专项审批后，才能另行决策是否放开非 synthetic 项目。

任何曾通过聊天或其他明文渠道共享的旧 Token 都不得进入本地配置、命令、测试或仓库，必须在服务商侧撤销后使用新 Token。
