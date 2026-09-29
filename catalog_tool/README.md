# 使用与设计说明

## 1. 工作流

```powershell
./catalog_tool/catalog.ps1 index .
./catalog_tool/catalog.ps1 stats
./catalog_tool/catalog.ps1 search --query '蓝牙 耳机' --price-field agent_price --min-price 80 --max-price 150 --limit 10
./catalog_tool/catalog.ps1 show --ids p_ID1 p_ID2
./catalog_tool/run.ps1 -ProductIds @('p_ID1','p_ID2') -PriceFields @('reference_price_b')
```

自然语言由助手理解，然后转成明确参数。无需额外模型调用、向量库、服务进程或网页。预算和 PPT 上的展示价格可以不同，必须分别选择；面向客户时按需求选择零售价等字段。

首次 `index` 传文件或目录；支持多个路径、递归发现 `.xlsx`，排除内部缓存、输出和 Excel 临时锁文件。后续 `index` 不传路径会刷新已注册来源。文件删除或搬家时显式 `remove-source 旧路径`，再导入新位置。源文件永不由工具删除。

`search` 返回紧凑 JSON，默认 10 条、最多 50 条，`--offset` 翻页；包含 ID、名称、原始价格、分类来源、文件/表/行。分类不明保留“未分类”。`show` 最多读取 10 个 ID，返回完整原始字段和数据提示，且重新核验源文件哈希。

| 参数 | 含义 |
| --- | --- |
| `--query '蓝牙 耳机'` | 所有词都要命中；默认仅查名称和型号，不做同义词推断 |
| `--scope all` | 扩展到描述、分类、品牌和供应商；结果附命中片段 |
| `--price-field agent_price` | 按配置映射的供货类价格；也可写确切原列名 |
| `--price-field reference_price_b` | 按配置映射的零售类价格；原标签保留 |
| `--min-price 80 --max-price 150` | 闭区间；必须明确价格字段；未知、空值、区间文本不当作 0 |
| `--sort price-asc` / `price-desc` | 同样必须给价格字段；非数值放在末尾 |
| `--category '数码'` | 同时匹配 `数码` 与 `数码/...` 子分类 |
| `--brand '品牌名' --supplier '供应商名'` | 精确匹配 |
| `--exclude '有线'` | 排除指定词，可多次使用 |
| `--has-image` | 至少有一张已识别的嵌入产品图或包装图 |

标准输入整份图册仍然支持：

```powershell
./catalog_tool/run.ps1 -InputFile './报价表.xlsx'
```

默认展示源表中的价格列；超过两列时要求 `-PriceFields` 显式选择最多两列。一次 PPT 最多 1000 款，按传入 ID 顺序生成，长说明自动续页。输出固定为 `outputs/产品图册.pptx`，可通过 `-OutputFile` 改到项目内部的指定位置。失败不会替换旧输出；成功后清除该次临时目录。

## 2. 多供应商与多品类配置

根目录可放 `catalog.local.json`，自动读取且不会提交 Git。首次可复制 `catalog.example.json`。全局参数位于子命令之前：

```powershell
./catalog_tool/catalog.ps1 --config './catalog.local.json' --index-dir './.catalog-index' index .
```

配置示例（此处均为示意名称）：

```json
{
  "aliases": {"name": ["产品名称", "商品标题"]},
  "detail_fields": ["功率", "容量", "材质"],
  "source_schemas": [
    {"match": "供应商甲*.xlsx", "aliases": {"agent_price": ["供货价"]}, "sheets": ["在售产品"]}
  ],
  "source_defaults": [
    {"match": "供应商甲*.xlsx", "supplier": "供应商甲"}
  ],
  "category_rules": [
    {"category": "数码/耳机", "keywords": ["耳机", "耳麦"]},
    {"category": "家居/杯壶", "keywords": ["保温杯", "水壶"]}
  ]
}
```

- 默认支持常见名称、型号、价格、卖点、图片等表头，规范字段见 `extract.py` 的 `ALIASES`。给某字段配置别名会替换该字段的默认列表；同一规范字段匹配多列时拒绝猜测。额外以“价”或“价格”结尾的列仍保留为独立价格。
- 每张表前 20 行中识别唯一表头，名称列必需，其他字段可缺省。可配置 `header_search_rows`、`sheets`；每张表支持一个连续产品表，合并单元格、页脚和多重表头需先规整。未识别的工作表会在入库结果列出。
- `source_schemas` 按文件名通配符覆盖导入配置，后匹配规则优先；规则中的 `aliases` 替换全局 `aliases` 后再与内置默认值合并。不同供应商能选用不同价格映射，避免“成本价”和“供货价”混为一列。
- `detail_fields` 追加需要展示的原始规格列；未列入的额外字段仍可在 `show.raw_fields` 查阅。通用模板不会自动展示所有自定义列。
- 原表品类优先，标记 `category_origin=source`；名称规则按顺序取首个命中，标记 `rule`。规则不推断产品功能，也不会改写原始资料。
- `source_defaults` 只补有明确依据的品牌/供应商，标记配置来源；禁止从其他产品复制属性。
- 通用配置不预设行业分类，品类数量随来源扩展；`stats` 显示总类数和最多 20 类，精确分类筛选覆盖全部类别。`facets --query '家居' --limit 20 --offset 0` 可检索/分页浏览类目，另可 `--field brand` 或 `supplier`。导航数量包含已入库记录；实际搜索会剔除过期来源。

样式单独配置 `style.local.json`：`brand`（无来源品牌时的明确默认值）、`brandColor`、`placeholderProductImageSha256`。默认品牌为空，不会给其他供应商套用旧品牌。品牌优先取产品记录。旧 `sendem.json` 仅作显式选用的兼容配置。

## 3. 数据准确性

- 图册展示源表缓存值，不执行公式或宏。不重新计算 Excel 公式；未缓存的公式列记录提示，缺值显示“未提供”。需要更新公式结果时先在 Excel 中重算并保存。
- 名称、型号、价格标签、价格文本及卖点均保留原始含义。换行可为排版调整；不推断币种或单位，不补写宣传语。
- 原表说明本身可能错贴。`--scope all` 只能证明文字命中；对功能性要求先 `show` 核对上下文，不能仅凭关键词承诺功能。
- 只读取锚定在对应产品行、已识别图片列的 Excel 嵌入 PNG/JPEG；浮动装饰图忽略，单格多图/其他格式报错。外链图、单元格 IMAGE 函数和特殊“单元格内图片”目前不解析，可按无图处理。
- 有产品图时展示产品图，另有包装图时作为缩略图；配置确认的占位图才可改用同一行包装图；两张均无则使用纯文字布局。
- 每页备注包含源文件名、工作表、行、单元格、产品 ID、源文件 SHA-256。备注随 PPT 交付，包含这些来源信息。

## 4. 索引结构与速度设计

`extract.py` 读 Excel 并保留原值 → `catalog_store.py` 增量写 SQLite → `catalog.py` 输出简短候选 → `run.ps1` 按 ID 提取资料 → `build.mjs` 排版 → `verify.py` 比对并发布。

本地 `.catalog-index/` 保存数据库与按 SHA-256 去重的图片缓存。库内保存来源元数据、结构化价格、原始记录、名称索引和全文索引。SQLite [FTS5](https://www.sqlite.org/fts5.html) 存储经过编码的 Unicode 单字/双字词元，查询先缩小候选，再核对真实连续子串，支持中文短词并避免把搜索内容当 SQL。

**增量策略：**相同文件大小、修改时间和配置摘要直接跳过；有变化时核对哈希，只重建变化的来源。一次导入在事务内完成，失败保留之前的索引。`index --verify-hash` 强制核对原文件；`index --rebuild` 重新解析并修复丢失或损坏的图片。更新暂不清理旧图片对象，避免删除仍被其他产品引用的图片；缓存占用会随来源版本增长。

**准确性与速度取舍：**普通搜索只检查文件元数据，对过期来源不给结果；罕见的“内容改动但大小和修改时间相同”要靠 `--verify-hash` 检出。`show`、PPT 选品阶段和发布前都会核验所选文件的实际哈希，选品阶段还核验图片。校验通过后才替换最终 PPT。

ID 来自源路径、工作表、型号（缺失时用名称）及同身份的出现序号。同来源唯一身份的行重排不改变 ID；文件移动、表名/型号变更或重复身份顺序变化需重新检索。配置改变会让旧索引过期，重新导入即可。开发时修改导入语义需同步递增 `catalog_store.py` 的 `IMPORT_VERSION`，让旧来源重新解析。

**减少上下文占用：**结果上限、详情按需、图片留在缓存、确定性筛选由代码执行。助手只读取少量候选和最终必要参数。新增价格列/类别靠配置或导入规则，不需要把每类商品都写成一套查询代码。

## 5. 环境、验证与公开检查

检索：Python 3.11+，SQLite 需启用 FTS5。依赖见 `requirements.txt`。Windows 包装器优先用 Codex 的 Python；其他环境直接 `python catalog_tool/catalog.py ...`。

PPT：Windows PowerShell、Codex 随附 Node.js/Python、`@oai/artifact-tool` 和 Presentations skill；`run.ps1 -RuntimeRoot ... -SkillDir ...` 可覆盖路径。构建过程验证包结构、画布、字体和重新导入，并逐页比对名称、序号、所选价格、完整说明及来源。机器校验不替代客户发出前的视觉抽查。

```powershell
python -m unittest discover -s catalog_tool/tests -v
python catalog_tool/benchmark.py --rows 10000
python catalog_tool/audit_public.py
```

基准使用合成数据，结果仅写终端，临时样本自动清理。真实图片、描述长度、源表大小、磁盘与机器性能会改变耗时。核心测试使用临时合成工作簿，不依赖私有业务文件；GitHub Actions 不运行依赖 Codex 桌面环境的 PPT 导出。

本机一次验证（2026-09-29）：142 款真实产品建库约 1.0 秒，典型检索约 0.5–1.5 毫秒；3 款产品/4 页 PPT 生成与核验约 3.6 秒。1 万条合成产品、100 类的建库约 2.0 秒，30 次检索中位数 64 毫秒、95 分位数 117 毫秒，返回 10 条时约 1807 字符。这些是本次实测值，不含助手推理时间，也不代表所有数据的性能上限。

预览注意：本机 Artifact Tool 的 PPT 重新导入预览曾出现部分中文标题缺字，原始直接渲染和 PPT XML 中的文字完整。遇到类似情况先对比直接渲染与实际 PowerPoint 显示，勿因预览异常删除源内容。

公开检查覆盖工作树中的已跟踪文件、所有可达历史版本及作者/提交者邮箱，检查凭据模式、个人邮箱、机器用户路径和不应提交的业务文件，只输出位置及规则，不回显秘密。它是定向检查，无法证明任意商业资料均不敏感；发布前仍应检查 Git 差异。

`.xlsx`、`.pptx`、数据库、图片缓存、`.env`、密钥、本地配置和构建目录均被排除。源报价、客户资料或产出不进入仓库；只提交代码、合成测试及通用文档。
