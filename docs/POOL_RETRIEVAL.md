# 产品资料、补查与报价管理

由 `catalog_tool/POOL_WORKFLOW.md` 绑定。需要整理旧数据、抽象需求、多条件检索或管理报价版本时读取。下面均为合成示例；JSON 放私有目录，禁止写入代码仓。命令前缀 `./assistant.ps1 run pool`。

## 1. 一次整理，重复使用

原始产品记录不修改。`add/import` 成功增加产品后，CLI 自动从本来源的明确“品牌：…”“容量：…”等原文补充资料；复杂规格和未知值留空。旧库执行 `derive`，也可 `derive --file 文件ID` 或 `--ids 少量ID`。这是确定性提取，不会按厂家、文件名套规则。

`quality --price-field retail_price` 返回全池缺失量、不可比较价格、部分导入来源及未知报价版本。不是这次查询的准确率。`review-queue --field category --limit 20` 分页取得待整理商品；整理后队列会缩小，继续从 offset 0 取即可。

Codex 先读原文；用 `enrich --records 文件.local.json` 保存判断：

```json
[{"id":"p_实际ID","revision":0,"facts":[
  {"field":"brand","value":"远行","origin":"source","quote":"品牌：远行","reason":"原文明确标注"},
  {"field":"category","value":"家居/杯壶","origin":"inferred","quote":"保温杯","reason":"根据品名分类"},
  {"field":"attr.capacity","value":500,"unit":"ml","origin":"source","quote":"容量：0.5L","reason":"等量单位换算"}
]}]
```

- `revision` 取 `show --ids ID --metadata` 的 metadata.revision；同值重试不重复写，不同值遇旧版本停止。每批最多 100 款、每款 20 个字段。
- 原文证据必须属于这款产品。category 可明确标记推断；品牌、供应商和文字属性的值必须出现在引文中。推断原文中哪个词是品牌，也应标为 inferred。含糊时不填。
- 字段支持 brand/category/supplier 和 `attr.<英文属性名>`。数值属性必须有原文数字及明确单位，支持体积、重量、长度、功率、电量、时间、噪声的常见等量换算。不能把多规格报价取最低值、把三瓶容量猜成整盒容量。
- 优先复用 `facets --field category` 的统一层级；“食品/月饼”是品类，“某品牌中秋礼盒”保留为原文。多品牌、纯包装、混装礼盒不强猜单品身份。
- `show --metadata` 默认最多八个补充字段；`--metadata-field attr.capacity` 可只看一个。原字段与补充字段分开输出。
- 修改有留痕：`history --kind product --id ID` 查看摘要；`history --event 数字 --max-chars 1000 --text-offset 0` 查看一段具体变更。原报价错误需要加入更正来源并管理替代关系，不覆盖旧事实。
- 误补的字段可用同一 enrich 合同设 value=null 撤销，仍要提供 revision、原文引用和理由，不带 unit。只移除补充层，不改原始记录。品牌、品类或规格的值发生变化，会解除对应的已核对同款组并返回 groups_requiring_review；原报价全部保留，重新核对后再 link，避免旧分组继续隐去不同商品。

## 2. 把口语变成有界检索计划

Codex 区分必须满足的条件与偏好，先查看实际价格角色和品类。脚本不硬编码节日/受众规则。下面是“100 元内的充电宝，自带线更好”的候选查询示例；是否自带线在结果原文中核对，不能擅自变成硬条件。

```json
{
  "version":1,
  "hard":{"price_field":"retail_price","maximum":100},
  "lanes":[{"query":"充电宝"},{"query":"移动电源"}],
  "limit":10,"per_lane":30,"diversity":true,"group_products":true
}
```

执行 `retrieve --plan 需求.local.json`。只有 Codex 负责自然语言理解；一次命令完成补查、ID 去重、排序、品类分散和覆盖提示。无需把整库塞进上下文。

### 合同

- `hard` 的所有条件约束每一路搜索。允许 price_field/minimum/maximum/category/brand/supplier/exclude/has_image/sort，以及 tags/tag_origin/file_id/exclude_categories/attributes/latest/include_history/series/price_labels/price_terms/product_group。
- 每个 hard 条件都要对应用户明确的必要要求或已确认口径。has_image 只表示有原始产品图片；“实物商品”与图片是否存在无关。用户没要求图片，不加 has_image。
- `lanes` 为 1..8 路；仅允许 query/scope/category/tags，不能修改价格或其他硬条件。默认 scope=all；一路里的字词按原有 AND 子串匹配。category/tag 与 hard 条件同时满足。
- 标签稀疏时**显式加入品类或文字搜索路线**。空标签结果不说明没有合适商品。空对象 `{}` 是明确选择在硬条件内浏览，默认会穿插不同品类，避免只取某文件开头。
- 品类与包装、用途、场合是不同维度。某个“礼盒”类目不覆盖所有盒装产品；只有确定产品本体类别时才设子类硬条件。语义不确定时，用父类和独立文字词补查，再核对内容。query 按空格分词后 AND 匹配，不做中文自动分词；不要把多个概念拼成长词期待语义匹配。
- `exclude_categories:["食品","数码"]` 排除这些层级，并排除无法确认类别的记录。不会把未分类当成“肯定不是食品”。
- `attributes:[{"field":"attr.capacity","minimum":500,"unit":"ml"}]` 做单位一致的范围筛选；文字属性用 `{"field":"attr.material","value":"不锈钢"}`。未知属性不满足硬条件。只有原文测量值参与筛选。
- `price_labels:["供货价","供货价格"]` 在大价格角色下进一步限定原始标签。`price_terms:{"currency":"CNY","unit":"只","tax":"included"}` 要求已核对的交易口径；未知不算满足。不能把参考价、成本价、供货价混用。
- 自动识别现已区分 retail_price / reference_price / reference_price_b / agent_price / supply_price / purchase_price / cost_price / sale_price。旧库保留原记录；旧存储角色与原始标签明显冲突时，默认角色查询排除并报告。核实实际价格含义后，可显式给 price_labels 选择原价列；交付始终保留该原始标签。不要为了兼容旧字段名把价格改成另一种含义。
- limit 为 1..50，per_lane 为 limit..50。等价词扩展最多 24 路，单路线最多四个变体；发生截断会明确报告。按价格排序时遵循价格顺序，不穿插品类。
- 返回每路总量/已读取量、候选原文片段、命中路线、同款报价的替代 ID、全池覆盖和 warnings。`truncated` 或未知字段提示必须被考虑；没有测过完整相关集合，就不能声称找全。
- 同组默认只展示三份替代报价摘要，`alternatives_more` 表示还有；`search --group 组ID --limit 10 --offset 0` 可逐页取得全部当前报价，保留本次价格等硬条件。需要复杂条件时，在原计划 hard 加 product_group 并设 group_products=false；单次仍有界，不能把代表报价说成最低报价。
- 软偏好如“体面、实用、适合长辈”由 Codex 根据候选事实判断，解释为建议。没有噪声资料就说“静音情况没写”，不能把候选当已满足静音。只有必要的缺失硬条件才向用户询问。
- 判断先看 facts_excerpt（包含原说明及未映射原始列），不能只看 attributes 是否已有结构化值。facts_length 超过片段长度时，按 show 的字段/原始列继续读取；没看完不能说“资料没写”。零结果或候选全部被拒绝时，检查词的切分、子类覆盖和缺失字段，最多两轮有依据的补查，仍不放宽用户硬条件。
- 属性硬条件因资料未结构化而为零时，可先在已确认预算/类别内分页读原文以整理资料；这一步的未核实商品不能交给用户当合格候选。用证据 enrich 属性后，重新执行包含原属性硬条件的计划。

### 复用等价叫法

`vocabulary --records 文件.local.json` 接受 `[{"kind":"query","terms":["充电宝","移动电源"],"reason":"日常等价叫法"}]`。这存进当前池的资料，不写进解析代码。kind 还支持 brand/supplier/category/`tag:occasion` 等标签种类。不要把上下位、相似风格或相关用途当等价词。扩大已存在的组时必须带齐原成员。

## 3. 报价版本与同款商品

`files` 的 quote 字段显示来源版本信息。上传顺序和文件修改时间不代表报价日期。

`source-update --records 文件.local.json`：

```json
[{"id":"d_实际ID","revision":0,
  "changes":{"series":"供应商甲-水杯系列","issued_on":"2026-09-01","status":"active"},
  "reason":"核对相同供应商报价范围和原文日期",
  "evidence":[{"ref":"filename","quote":"2026-09-01"}]}]
```

- evidence 可以引用 `inspect` 的文本 ref；filename 只引用真实原文件名。日期必须有完整年月日的原文依据；没有日期就保持未知。series 是经核对的同一供应商/同一报价范围，不按相同品牌随意合并。
- `changes.status` 可设 active/withdrawn。新来源明确完整替代旧来源时，在新来源 changes 中加入 `supersedes:{"id":"旧文件ID","revision":旧版本号}`；要求同系列、严格较新的日期及完整导入。部分导入不能替代整份旧文件。
- 默认搜索不返回 withdrawn/superseded 来源；`search --include-history` 显式查看历史。`search --latest` 或计划 hard.latest=true 仅返回有系列、有日期、日期唯一较新且完整导入的来源。日期相同、未知或较新文件只导入一部分时，不冒充已确定最新版。
- 不同来源的同款仍保留各自价格。`link --records` 接受 `[{"group":"内部SKU标识","ids":["ID1","ID2"],"reason":"已核对品牌型号规格一致","evidence":{"ID1":"型号原文","ID2":"型号原文"}}]`。所有成员须有相同的已知品牌和型号；已知不同规格/变体会拒绝。同名不是同款，未知不自动合并。分组只折叠候选，报价记录不会删除；扩组要带齐原成员。

`offer-terms --records` 保存商品**规范价格字段**的交易条件：

```json
[{"id":"产品ID","field":"retail_price","revision":0,
  "terms":{"currency":{"value":"CNY","quote":"人民币"},
           "unit":{"value":"只","quote":"单位：只"},
           "tax":{"value":"included","quote":"含税不含运"},
           "shipping":{"value":"excluded","quote":"含税不含运"}}}]
```

terms 支持 currency/unit/tax/shipping/moq，全部需要本产品原文证据；不要根据“元”猜币种。tax/shipping 值为 included/excluded，未知不填。moq 必须有“起订量：12”或“12只起订”等明确语境，不能引用价格或容量数字。`show --metadata` 返回当前修订号；具体证据见 offer 历史事件。

## 4. 选择页和验证边界

选择仍由用户勾选。新会话冻结来源、补充资料、推荐标签和报价条件的上下文；选好后这些内容有变化会要求重新展示，不能带着旧推荐理由偷偷导出。旧会话兼容保留，导出时仍检查来源是否撤回/被替代及原件完整性。

“某字段在资料里出现”仍不等于模型理解了正确的商品关系。入库时需核对名称、参数、价目和图片所属商品。未知的供应商、原文件缺失的日期和不能拆开的组合价，不能靠模型补成确定事实。
