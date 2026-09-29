# pool · 持续入库 → 检索 → 勾选 → PPT

命令前缀 `./assistant.ps1 run pool`（下文省略）。默认库 `data/product-pool/`；测试时在子命令前加 `--index-dir 私有测试目录`，全程用同一目录。自然语言理解只在 Codex，不调用额外模型服务。

## 用户交付文件

1. `add 路径` 按文件内容哈希保存原件。`duplicate` 表示已存在，不重新抽取；同名但内容不同会累积加入。`files` 分页查看 `ready/partial/pending`，不要把 pending 当作产品已入库。
2. XLSX 自动入库或返回 `needs_mapping`；异形表读 [来源映射](../docs/SOURCE_MAPPING.md)，借原 `catalog inspect` 看坐标，然后 `add 路径 --map 私有映射.local.json`。禁止为文件名/品牌写解析分支。
3. PDF / PPTX / DOCX / TXT / CSV / XLS 等：`inspect --file 文件ID --limit 20` 看有界证据；按 `--page` / `--ref` / `--text-offset` 深读。Codex 判断产品粒度，按 [入库合同](../docs/POOL_IMPORT.md) 写私有 JSON，再 `import --file 文件ID --records 文件.local.json`；可每次只加一款，同一来源定位重试不重复。
4. 图片/扫描件先看原图；PDF 可 `render --file 文件ID --page 1`。逐字观察后 `observe` 留显式视觉转录，再引用其 ref。无法识别的价格不猜；视觉转录与原生文字验证区分标记。`.doc` 等不支持格式先明确转换，不能当空表成功。
5. 新增记录后入口自动整理原文明确标注的品牌/规格。`quality --price-field 实际价格字段` 核对缺失及覆盖；旧库可 `derive`。需要补分类/品牌、修正检索资料或管理新旧报价，读 [资料与检索合同](../docs/POOL_RETRIEVAL.md)。缺价格或图片仍可入库，同名新文件不自动覆盖旧报价。

## 用户描述需要

1. 把口语拆成硬条件（价格口径、预算、品类、来源等）和推荐条件（场合、对象、用途、风格）。不知道价格口径且会影响结果时才问；别把参考价当供货价。
2. `facets --field price` / `facets --field category` 查实际字段。`facets --kind occasion` / `--kind audience` 查已登记推荐标签；标签种类可扩展。
3. 单一明确条件可 `search`；抽象、多条件、跨品类需求读 [资料与检索合同](../docs/POOL_RETRIEVAL.md)，写一个私有计划后 `retrieve --plan 路径`。所有补查共用硬条件，工具合并候选并报告覆盖；已登记的同义词可复用。不在多轮查询中悄悄放宽预算。
4. **标签没有命中不等于没有适合的商品。** 查看 `stats.tagged_products`；有界读取候选事实，必要时按 [入库合同](../docs/POOL_IMPORT.md) `annotate` 场合/对象等标签，附来源证据和推荐理由。只读到“礼盒”可以形成送礼建议，不能推断认证、功效、材质或受众安全。
5. `show --ids 少量ID` 核对；默认说明 400 字，可按字段续读；`--metadata` 查看补充资料及报价版本。`source` 是原文明示，`inferred` 是 Codex 判断。没有证据满足的偏好，要用口语说明“这个资料里没写”，不能说已满足；对用户尽量简短好懂。

## 让用户选择并导出

1. `choose --ids ID1 ID2 --price-fields retail_price --title '新年礼品候选'` 冻结候选与展示价格，返回 session_id 和 HTML 路径。价格必须对候选均有效；不同口径不可混选。
2. `open --session 会话ID` 启动/复用本机选择服务，返回 URL。通过 Codex 打开这个 URL，让用户只勾选；**不要直接打开 file://HTML**，那样不能保存选择。无须用户导入、编辑或回传 JSON。
3. 用户说“选好了”后，`selection --session 会话ID` 读已保存 ID；空选择必须等待，不能代选。
4. `ppt --session 会话ID` 仅导出用户所选及页面展示价格，先核验再替换唯一 `outputs/产品图册.pptx`。会话封存后不可改选；改选需新建会话。出错保留旧 PPT。
5. 服务只监听 127.0.0.1，进程隐藏运行；封存/`close --session` 或 1 小时后退出。服务退出后选择仍保留，开放会话可再次 open。最终只交付 PPT；HTML 是过程中使用的选择界面。

页面勾选即时反馈，后台按修订号串行保存；快速连续操作保留最后的选择，不禁用整页或重建卡片。请求失败会重新核对数据库、显式提示未保存；无法核对时停止编辑。`open` 会更新旧会话的界面模板，保留候选事实与已保存选择；已打开的旧页面刷新一次即可使用新界面。

修改数据库/多格式/选择协议时读 [产品池设计](../docs/PRODUCT_POOL.md)。主代理唯一修改正式库；模型实验用隔离测试库。检查 `python -m unittest discover -s catalog_tool/tests -v`，端到端还需真实浏览器和 PPT 运行时。
