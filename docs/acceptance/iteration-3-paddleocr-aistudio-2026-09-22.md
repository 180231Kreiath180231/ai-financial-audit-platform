# PaddleOCR AI Studio 合成数据专项接入验收（2026-09-22）

## 范围

本轮实现 PaddleOCR AI Studio 异步 Jobs API 的合成数据专用纵向切片。自动化测试使用注入式模拟传输，不访问真实服务；没有使用用户在对话中提供的旧 Token。

关联需求：PRD-DOC-003、PRD-MDL-001 至 005、PRD-OFF-001、F05、F07、F12。

## 已实现

- 专用 `paddleocr_aistudio` Provider、固定已批准 Jobs Endpoint、`PaddleOCR-VL-1.6` 与视觉/文件上传能力约束。
- Windows DPAPI Access Token 保存、轮换、清除和不回显行为复用既有安全边界。
- strict offline、项目授权、synthetic 标志三重运行门禁；非 synthetic 项目在调用前阻断。
- 扫描页逐页渲染和 multipart PNG 上传，不上传整份 PDF 或原文件名；单页上传前执行 20 MB 本地上限检查。
- Job 提交、状态轮询、JSONL 下载和 Markdown 文本映射；忽略所有返回图片。
- 超时、限流、余额、认证、服务不可用、未知状态、无效 JSON/JSONL、空结果和本地安全点中断错误映射。
- HTTPS 结果地址校验、私网地址阻断、重定向拒绝和 16 MB 响应上限。
- 页级结果和统一模型调用审计保存 Job ID、最小数据范围、图像摘要和远端清理状态；创建 Job 后的失败与中断也保留该生命周期信息。
- 设置页提供 PaddleOCR 类型、固定 Endpoint、遮蔽 Token 输入和固定能力模型档案。

## 自动化结果

- 后端 pytest：56 项通过。
- 前端 Vitest：13 项通过。
- 前端 ESLint 与生产构建：通过。
- Playwright：8 项通过，6 项按设备条件跳过。

## 安全结论

- 测试未产生任何真实外部请求。
- 旧 Token 未写入源码、数据库、命令、日志、测试或构建产物。
- 真实审计项目仍返回 `OCR_REMOTE_RETENTION_UNVERIFIED`，传输函数不会被调用。
- 服务商未提供远端删除接口，因此成功记录明确显示 `remote_cleanup_status=unsupported`。

## 尚未完成

- 用户需撤销已暴露旧 Token，并通过设置页保存新 Token。
- 尚未使用新 Token 和无业务含义的合成 PDF 完成真实网络联调。
- 尚未取得服务商远端保留期限、删除能力和数据处理条款，真实审计资料不能外发。
