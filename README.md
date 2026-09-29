# XLSX 产品检索与 PPT 图册

给 Codex 使用的本地选品工具：**观察来源布局 → 登记映射 → Excel 增量入库 → 精确筛选 → 按 ID 生成 PPT**。格式适配只在首次或结构变化时进行。

```powershell
# 首次导入或刷新：仅解析发生变化的工作簿
./catalog_tool/catalog.ps1 index ./data

# 确认价格字段，随后按明确口径筛选
./catalog_tool/catalog.ps1 stats
./catalog_tool/catalog.ps1 search --query '耳机' --price-field agent_price --max-price 100 --limit 10
./catalog_tool/catalog.ps1 show --ids p_返回的产品ID

# 选择产品及要向客户展示的价格字段
./catalog_tool/run.ps1 -ProductIds @('p_返回的产品ID') -PriceFields @('reference_price_b')
```

默认只交付 **`outputs/产品图册.pptx`**。重做时先验证新文件，再替换旧文件。数据、图片、索引与本地配置都留在本机，仓库只保存代码和通用说明。

## 能力

- 多文件、多工作表、合并记录、分段表和重复卡片；字段含义由 Codex 观察后写入可复用的坐标映射。新增来源不需要给解析器添加厂家分支。
- SQLite FTS5 中文检索，支持名称/型号、价格范围、品类、品牌、供应商、排除词和分页。
- 默认每次只返回 10 个简短候选；详情默认说明最多 400 字，可按字段和字符窗口续读。完整原文直接送入 PPT。
- 原始价格和描述不改写；未知价格不参与数值筛选；每页备注记录来源、行号、单元格和源文件哈希。
- 单元格图片和浮动图都保留来源；合并名称下的规格变体独立保留。组合价格文本不猜算，Excel 错误价格不能发布。
- 索引过期、表头/固定范围变化或图片损坏时显式报错；生成前后核验来源，逐页比对名称、价格及完整说明。

`data/` 整目录已忽略，公开检查同时阻止该目录及历史中的私有材料。源文件、私有映射、索引和验证产物不提交。

## 环境与范围

检索可独立运行：Python 3.11+、启用 FTS5 的 SQLite、`pip install -r catalog_tool/requirements.txt`，然后将上面的 `catalog.ps1` 换为 `python catalog_tool/catalog.py`。

PPT 导出使用 Windows Codex 桌面版随附的 `@oai/artifact-tool`、Python 和 Presentations skill。`run.ps1` 支持指定运行时路径；普通 Python 环境只能直接运行检索与核心测试，不能单独完成 PPT 导出。

详细配置、准确性边界及设计见 [工具说明](catalog_tool/README.md)。首次接入异形表看 [来源映射](docs/SOURCE_MAPPING.md)，可选分工看 [代理工作流](docs/AGENT_WORKFLOW.md)。助手从 [AGENTS.md](AGENTS.md) 的短流程开始。
