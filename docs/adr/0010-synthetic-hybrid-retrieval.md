# ADR-0010：合成向量与内存混合检索验收通道

- 状态：已接受
- 日期：2026-09-22
- 关联：PRD-RET-002、PRD-RET-003、PRD-RET-004、F06、F07

## 背景

检索分块与向量索引版本契约已经完成，但真实 Embedding 服务商与数据处理政策仍未批准。系统需要在不引入真实外发、不把模拟质量包装成生产能力的前提下，验证“索引构建 → 向量召回 → 关键词融合 → 页级证据”的完整技术链路。

## 决策

- 仅合成项目可以显式构建 `synthetic-hash-embedding-v1` 测试索引；真实项目在 API 层返回可操作的 409 错误。
- 合成向量由确定性的字符与双字特征哈希生成，固定为 64 维。它不是本地模型，不代表任何真实 Embedding 的语义质量。
- 向量以版本化 BLOB 保存，当前后端为 `memory_cosine`。查询时只把满足项目结构化筛选的向量载入有界候选集。
- 关键词候选与向量候选各不超过 50 块，使用 RRF 融合，最终返回不超过 30 个可回溯分块。
- 每个返回块保留文档、页码、块号、精确原文、解析方式和解析版本；纯向量召回明确标记为“合成语义命中”。
- 索引构建写入项目审计事件，并明确记录 `external_request=false`。页面分块变化后，旧索引立即标记为过期并拒绝查询。
- 前端只有合成项目显示构建入口；构建成功后由用户显式开启或关闭混合检索，加载、错误、重试与当前模式均展示真实状态。

## sqlite-vec Windows 探测

按照项目官方 Python 示例，在当前 Windows、Python 3.12 环境使用临时依赖 `sqlite-vec==0.1.9` 完成以下探测：

1. 加载扩展并读取 `vec_version()`；
2. 创建 `vec0` 三维浮点虚拟表；
3. 插入向量；
4. 执行 KNN 查询并得到距离 `0.0` 的正确结果。

探测结果为 SQLite `3.53.1`、sqlite-vec `v0.1.9`，当前 x86-64 Windows 环境兼容。sqlite-vec 官方仍将项目标为 pre-v1，因此本轮不把临时探测包写入生产依赖或锁文件；正式采用前还需完成持久化迁移、打包、回滚和性能验收。

参考：[官方安装说明](https://github.com/asg017/sqlite-vec/blob/main/site/getting-started/installation.md)、[官方 Python 示例](https://github.com/asg017/sqlite-vec/blob/main/examples/simple-python/demo.py)。

## 边界

- 本决策没有批准任何真实数据外发、外部 Embedding 服务商或本地 Embedding 模型。
- 合成索引不能用于真实项目，也不能作为真实语义召回率验收结果。
- DuckDB 指标联合取证、真实 Embedding 批处理、sqlite-vec 正式持久化后端和模型切换重建仍未完成。
- PRD-RET-002 与 PRD-RET-003 仍处于合成链路验证阶段，不宣称生产验收通过。
