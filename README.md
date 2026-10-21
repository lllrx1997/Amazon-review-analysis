# Review Lens · 亚马逊评论分析工具

面向内部团队的单 ASIN MVP：Bright Data 获取美国站评论，DeepSeek 翻译与分类，页面展示买家反馈及原文证据，并支持 Excel / Markdown 导出。

## 已实现的功能

- 单个 ASIN 输入、真实阶段进度、失败原因和忙碌提示，不排队。
- 最新最多 100 条的采集目标，无默认时间窗口或星级配额；供应商是否保证排序、上限和范围需实测，未确认时在报告中提示。
- 样本总数、1–5 星数量、样本差评占比。
- 1–2 星差评分类、条数和证据；4–5 星认可点与好评摘要；3 星单独反馈。
- 全星级评价主题，以及有证据时的使用情境洞察。
- 原文和中文翻译证据抽屉、星级筛选、Excel 与 Markdown 导出。
- AI JSON 与引用校验、分批翻译、有限重试、分类统一、部分失败提示。

不含账号、历史记录、数据库、批量对比、文件导入、自建爬虫、人工修改与主观评分。

## 项目结构

```text
frontend/                 Next.js + TypeScript 页面
src/ad_optimizer/
  api.py                  FastAPI、临时任务、状态查询
  config.py               服务端环境变量
  providers.py            Bright Data 采集及数据清洗
  analysis.py             DeepSeek 分析与证据校验
  models.py               数据合同
  exports.py              Excel / Markdown 导出
tests/                    业务流程与外部接口合同测试
.env.example              后端配置样例，不含密钥
```

## 本地启动（Windows PowerShell）

需要 Python 3.12+、uv、Node.js 20.9+ 和 npm。前后端分别占用一个终端。先在项目根目录执行：

```powershell
uv sync
Copy-Item .env.example .env
```

编辑根目录 `.env`，填写以下配置。不要将真实 Key 放进前端或提交到 Git：

| 配置 | 填什么 |
| --- | --- |
| `BRIGHT_DATA_API_KEY` | Bright Data API Token |
| `BRIGHT_DATA_DATASET_ID` | 账号中 Amazon Reviews 采集器的 Dataset ID，不是控制台页面 URL |
| `LLM_BASE_URL` | 默认 `https://api.deepseek.com`；兼容服务可填自己的 Base URL，不含 `/chat/completions` |
| `LLM_MODEL` | 账号当前可用模型名，示例为 `deepseek-flash`，可自行修改 |
| `LLM_API_KEY` | 模型服务 Key |

如果地址已经包含 `/v1`，直接保留，程序在其后追加 `/chat/completions`。兼容服务必须支持 Chat Completions 和 `json_object` 输出；不是任意地址与 Key 都能直接兼容。

后端终端（根目录）：

```powershell
uv run ad-optimizer
```

前端终端：

```powershell
cd frontend
npm ci
npm run dev
```

访问 http://127.0.0.1:3000 。后端接口说明：http://127.0.0.1:8000/docs 。健康检查：http://127.0.0.1:8000/api/health 。未配置密钥时页面会提示配置待完成，不使用演示数据伪装真实采集。

首次交付时依赖已安装、锁文件已生成；上述安装命令主要用于新环境。修改 `.env` 后重启后端。

## Bright Data 必须先核对的参数

适配器直接调用 `/datasets/v3/trigger`，取得 `snapshot_id` 后轮询 `/progress/{snapshot_id}`，再下载 `/snapshot/{snapshot_id}?format=json`。

`.env` 中的 `BRIGHT_DATA_INPUT_JSON` 会与服务器生成的商品 URL 合并，默认 `{"numOfReviews":100}`。这个字段名必须与**你账号中的 Amazon Reviews 采集器输入定义**核对。常见数量字段存在时会同步为 `MAX_REVIEWS`，不代表供应商一定支持它。

`BRIGHT_DATA_QUERY_JSON` 用于供应商定义在查询字符串里的额外参数。不要未经核对就加入所谓排序参数。默认不发送 `pastDays`，但省略后是否真的不限时间也要核实。

以下标志默认保持未确认，只有经过接口定义和真实结果验证后才能更改：

- `BRIGHT_DATA_LATEST_VERIFIED`：是否确认在采集阶段按最新排序。
- `BRIGHT_DATA_LIMIT_VERIFIED`：是否确认供应商端真的限制采集数量。
- `BRIGHT_DATA_SCOPE`：`unknown`、`parent_page`、`child_only` 或 `mixed`；描述当前采集器已确认的范围，不是根据 ASIN 字符猜测的结果。不同商品行为不一致时保持 unknown。

本地排序无法证明获取到的是全商品最新 100 条，本地截取无法证明供应商只采集了 100 条。真实测试前不要把未确认标志改成 true 来消除提示。

采集器支持的原文字段包括 `review_text/review_content/content/text/body`，星级支持 `rating/review_rating/review_stars`。如果实际返回结构不匹配，需要根据实际样本扩充 `providers.py`，不能让 AI 填补缺失数据。

## 统计和证据口径

有效样本是清洗、去重后进入本次分析的评论。差评样本占比为 1–2 星条数除以所有有效样本条数，包含 3 星在分母中；不代表商品整体差评率。类别按不同评论 ID 计数，不计算类别占比。

模型必须引用真实评论 ID 和连续原文片段。后端检查引用和分组，并计算条数，页面从保存的原文读取证据。AI 推测被单独标记为“尚需验证”，不代表确定性故障判断。自动校验只能排除一部分错误，仍需人工核对语义和翻译。

部分评论分析失败时保留星级统计，但明确显示已分析数量，摘要及分类只代表成功分析部分。全部模型失败时可查看已获取原文，导出将标明分析未完成。

### 评论有原文，但没有 AI 分析结果怎么办

这表示数据采集成功，模型调用或返回结果校验失败，并不代表商品没有相关反馈。后端会返回具体原因：

| 错误码 | 含义与处理 |
| --- | --- |
| `LLM_SCHEMA_INVALID` | 模型漏掉必填字段或字段类型错误；系统会将缺失位置反馈给模型重试，持续失败时检查模型结构化输出兼容性 |
| `LLM_OUTPUT_TRUNCATED` | 输出达到 token 上限；减少 `LLM_BATCH_CHARACTERS`，或在模型支持范围内增加 `LLM_MAX_TOKENS` |
| `LLM_EVIDENCE_INVALID` | 引用不存在、星级分组错误或引文不是原文；不会跳过校验强行展示结论 |
| `LLM_JSON_INVALID` / `LLM_OUTPUT_EMPTY` | 返回了无效 JSON 或空内容 |
| `LLM_REQUEST_ERROR` | 模型接口返回 HTTP 错误，核对地址、模型、参数支持及服务额度 |
| `LLM_AUTH_ERROR` / `LLM_TIMEOUT` | 鉴权失败或调用超时 |

系统给模型提供完整 JSON Schema，重试时说明具体校验错误，并按最多 5 条评论及输出预算联合控制批次大小。`LLM_BATCH_CHARACTERS` 是上限，实际批次可能更小。DeepSeek 官方接口使用非思考模式，将响应预算留给翻译和分析 JSON；其他兼容服务不发送这一专有参数。参见 [DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)。

重试仍失败但返回中有部分可核验内容时，系统会分别校验翻译及每项反馈，保留有效结果。任何证据不合格的反馈都会整项排除，不通过删除几条证据来强留描述。此类报告标记为“部分完成”，说明缺失情况，不因一个可选洞察缺字段而清空整批内容。全部分析失败时，前端显示明确失败提示及原文，不展示空白分析图表。

修改后端代码或配置后需重启 FastAPI 才生效。任务结果仅保存在内存，重启前请先导出仍需保留的原始评论。已失败的旧任务不会自动变为成功，需要重新提交。前端开发模式会更新页面；生产模式需重新构建并重启。

## 验证命令

根目录：

```powershell
uv run pytest -q
```

前端：

```powershell
cd frontend
npm run typecheck
npm run build
```

测试使用隔离的供应商/模型替身或 HTTP MockTransport，不会请求付费采集服务。真实验收需自行配置服务端 Key，输入一个已知 ASIN，对照原评论抽查 20 条，不足则全查。

## 运行和部署限制

### 耗时与性能设置

- 模型批次采用有上限的并发，默认 `LLM_CONCURRENCY=3`，不是无限并发，也不改变单 ASIN、无队列的产品规则。限流时可降低为 1 或 2。
- 模型连接在一次分析中复用，减少每批重新建立连接的开销。
- 每批默认最多尝试 `LLM_MAX_ATTEMPTS=2` 次；已有有效翻译和核心反馈时优先逐项保留，不因单个可选内容失败重做整批。
- `LLM_TIMEOUT_SECONDS=90` 控制单次 HTTP 请求等待。最后的同义分类整理最多等待 30 秒，超时保留已经验证的分类。
- 采集完成后立即展示原文与星级统计，分析内容随批次完成更新；阶段进度显示已处理条数及已通过分析条数。尚未结束的数字和分类可能变化，不能作为最终报告导出。
- 进度轮询先获取小体积状态，结果版本变化时才获取完整评论报告，避免反复传输相同原文。
- 页面显示采集、分析及总耗时，以便定位下一次实际运行的瓶颈。采集服务尚未返回时，优化前端不会缩短供应商执行时间。

这些优化不承诺固定完成秒数。并发收益取决于模型限流、评论长度、供应商负载和校验失败情况，不应为了提速取消证据校验。

- 后端必须单实例、单 worker；临时任务保存在内存，重启后不可恢复。
- 默认同时一个任务，无队列。结果默认完成后保留 2 小时，之后清理。
- Next.js 通过 `/api` 代理到 FastAPI，默认后端地址 `http://127.0.0.1:8000`。更改地址用前端服务端环境变量 `BACKEND_URL`，随后重新构建并重启前端。
- 本地启动仅监听回环地址。团队部署时通过内网反向代理统一提供 HTTPS 入口，不需额外开放未受限的后端接口。
- 生产前端使用 `npm run build`、`npm run start`；后端使用 `uv run ad-optimizer`，不使用多 worker。
- 日志不应记录 Key 或完整评论。调用前核对供应商许可与向模型传输数据的适用条件。

详细需求和设计见 [阅读指南](./文档阅读指南.md)、[PRD](./PRD.md)、[Spec](./Spec.md)、[流程图](./逻辑图与流程说明.md)、[技术栈](./技术栈与部署方案.md)。
