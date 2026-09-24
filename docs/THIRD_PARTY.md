# 第三方依赖清单

本清单记录第一版直接依赖。准确版本以 `uv.lock` 和 `frontend/package-lock.json` 为准；发布包还应归档各依赖的完整许可证文本和传递依赖清单。

## 生产依赖

| 依赖 | 当前锁定版本 | 用途 | 许可证 | Windows / 体积说明 |
|---|---:|---|---|---|
| React / React DOM | 19.3.0 | 生产界面与状态呈现 | MIT | 浏览器端；无常驻服务 |
| @phosphor-icons/react | 2.1.10 | 统一矢量图标 | MIT | 浏览器端；可 Tree-shaking |
| pdfjs-dist | 5.7.284 | 本地 PDF 阅读、页码和缩放 | Apache-2.0 | Worker 约 1.2 MB，按需加载 |
| FastAPI | 0.141.1 | 本地 REST API 与边界校验 | MIT | 仅监听 `127.0.0.1` |
| Uvicorn | 0.53.0 | 本地 ASGI 服务 | BSD-3-Clause | Windows 可运行 |
| Pydantic | 2.13.5 | 版本化请求与响应 Schema | MIT | 含 Windows wheel |
| pypdf | 6.19.0 | PDF 完整性检查与原生文本提取 | BSD-3-Clause | 纯 Python，低集成风险 |
| openpyxl | 3.1.5 | 基于版本化模板生成 Excel 风险清单、规则明细和证据索引 | MIT | 纯 Python；Windows 可运行；不需要本机安装 Excel |
| python-docx | 1.2.0 | 基于版本化模板生成 Word 审计工作成果包 | MIT | 纯 Python API；依赖 lxml；不需要本机安装 Word |
| pypdfium2 | 5.13.0 | 扫描页逐页本地栅格化 | Apache-2.0 OR BSD-3-Clause；PDFium 为 BSD-style | Windows x64 wheel 约 3.9 MB；无独立进程 |
| Pillow | 12.3.0 | 将单页位图编码为临时 PNG | HPND | 页面处理结束立即释放并删除临时文件 |
| Requests | 2.34.2 | PaddleOCR HTTPS、multipart 单页上传和异步 Job 轮询 | Apache-2.0 | 纯 Python 通用 wheel 约 73 KB；设置超时、响应上限并拒绝重定向 |
| python-multipart | 0.0.32 | 多文件上传解析 | Apache-2.0 | 仅本地请求 |
| psutil | 7.2.2 | CPU、内存与磁盘状态 | BSD-3-Clause | 提供 Windows wheel |
| DuckDB Python | 1.5.5 | 科目余额表明细与确定性规则结果的嵌入式分析存储 | MIT | Python 3.12 Windows x64 wheel 约 13 MB；无独立服务 |

## 开发与测试依赖

| 依赖 | 当前锁定版本 | 用途 | 许可证 |
|---|---:|---|---|
| Playwright Test | 1.63.0 | 桌面与移动端端到端测试 | Apache-2.0 |
| Vitest | 3.2.7 | 前端单元测试 | MIT |
| Testing Library | 锁文件版本 | 可访问语义查询与交互测试 | MIT |
| pytest | 8.4.2 | 后端单元与集成测试 | MIT |
| HTTPX | 0.28.1 | 后端 API 测试客户端 | BSD-3-Clause |

第一版未引入 GPL、AGPL、Redis、Celery、独立向量数据库、对象存储或模型 SDK。
