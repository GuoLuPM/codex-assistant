# XLSX 产品检索与 PPT 图册

给助手使用的本地选品工具：**Excel 增量入库 → 精确筛选 → 查看候选原始资料 → 按 ID 生成 PPT**。

```powershell
# 首次导入或刷新：仅解析发生变化的工作簿
./catalog_tool/catalog.ps1 index ./你的表格目录

# 确认价格字段，随后按明确口径筛选
./catalog_tool/catalog.ps1 stats
./catalog_tool/catalog.ps1 search --query '耳机' --price-field agent_price --max-price 100 --limit 10
./catalog_tool/catalog.ps1 show --ids p_返回的产品ID

# 选择产品及要向客户展示的价格字段
./catalog_tool/run.ps1 -ProductIds @('p_返回的产品ID') -PriceFields @('reference_price_b')
```

默认只交付 **`outputs/产品图册.pptx`**。重做时先验证新文件，再替换旧文件。数据、图片、索引与本地配置都留在本机，仓库只保存代码和通用说明。

## 能力

- 多文件、多工作表、不同表头；分类可来自原表或可配置的名称规则。
- SQLite FTS5 中文检索，支持名称/型号、价格范围、品类、品牌、供应商、排除词和分页。
- 默认每次只返回 10 个简短候选；详情按需读取，避免助手反复扫描整库。
- 原始价格和描述不改写；未知价格不参与数值筛选；每页备注记录来源、行号、单元格和源文件哈希。
- 索引过期、表头歧义或缓存图片损坏时显式报错；生成前后核验来源，逐页比对名称、价格及完整说明。

## 环境与范围

检索可独立运行：Python 3.11+、启用 FTS5 的 SQLite、`pip install -r catalog_tool/requirements.txt`，然后将上面的 `catalog.ps1` 换为 `python catalog_tool/catalog.py`。

PPT 导出使用 Windows Codex 桌面版随附的 `@oai/artifact-tool`、Python 和 Presentations skill。`run.ps1` 支持指定运行时路径；普通 Python 环境只能直接运行检索与核心测试，不能单独完成 PPT 导出。

详细配置、准确性边界及设计见 [使用与设计说明](catalog_tool/README.md)。助手从 [AGENTS.md](AGENTS.md) 的短流程开始。
