# 迭代二安全骨架验收记录（2026-09-22）

## 范围

本轮只实现多模型网关的安全配置与 Fake Provider 验收路径，不连接真实模型、OCR、Embedding、Rerank 或远端文件接口。测试数据和自检提示均为 synthetic 数据。

关联需求：PRD-MDL-001 至 005、PRD-OFF-001、F04、F05、F12。

## 已实现

- Registry Schema 版本 2：服务商、模型能力档案、调用记录、严格离线设置和项目级外发授权。
- Windows DPAPI 当前用户范围密钥存储；SQLite 仅保存引用，密钥不回显。
- 服务商和模型档案支持新增、编辑、启用与停用；密钥支持保留、轮换和显式清除。
- OpenAI-compatible 服务商配置校验，只允许 HTTPS，禁止把 Authorization 放入普通请求头。
- 文本、视觉、JSON Schema、工具调用、Embedding 和文件上传能力档案。
- 全局严格离线与项目显式授权双重门禁。
- Fake Provider 能力路由、自检响应、实际模型记录和 SHA-256 请求摘要。
- OpenAI-compatible 适配器支持 Bearer 认证、超时、有限退避重试、Token 与费用记录。
- 设置页覆盖深色、浅色、桌面、375×812 窄屏和 812×375 手机横屏布局。

## 自动化结果

统一门禁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

结果：前端 ESLint、5 项 Vitest、生产构建、Ruff 和 27 项 Pytest 全部通过。

浏览器验收：

```powershell
npm.cmd --prefix frontend run e2e
```

结果：5 项适用场景通过，3 项按目标视口有意跳过。新增覆盖设置页严格离线状态、项目授权禁用态、服务商新增与编辑，以及 Fake Provider 自检的“外部请求 0 次”结果。

## 安全专项验证

- DPAPI 文件和 Registry SQLite 均不包含测试密钥明文。
- 严格离线开启时，外部模型路由返回 `OFFLINE_MODE_BLOCKED`。
- 全局离线关闭但项目未授权时，返回 `PROJECT_EXTERNAL_ACCESS_REQUIRED`。
- 调用记录保存请求 SHA-256 摘要，不保存测试提示词原文。
- 适配器覆盖 401/403、余额不足、429、服务不可用、超时、无效 JSON 和响应 Schema 异常。
- 密钥轮换后旧 DPAPI 密文被移除，审计轨迹仅记录 `rotated`、`cleared` 或 `preserved`。
- 浏览器控制台无错误；设置页在 375px 竖屏和手机横屏下无横向溢出。

## 尚未完成

- 未使用真实测试密钥验证两家文本模型和一家视觉模型。
- 真实调用尚未接入用户可执行的业务任务，因此不宣称 F04、F05 完整通过。
- 缓存、备用模型自动切换和真实网络层阻断仍待后续验收。
- 配置删除仍未实现；后续需要二次确认和关联模型保护。

## 后续进展

缓存、备用模型自动切换和配置安全删除已在后续增量中完成，见
[迭代二网关闭环增量验收](iteration-2-routing-cache-2026-09-22.md)。真实服务专项验收仍未完成。
