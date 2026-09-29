# XLSX 产品图册生成器

将报价表中的产品名称、序号、代理价、参考价B、功能特点和嵌入图片转换为可编辑的 PowerPoint 图册。每款产品至少一页；说明过长时自动续页。生成后逐页核对标题、序号、价格和说明文字，不补写源表没有的数据。

## 使用

在项目根目录运行：

```powershell
.\catalog_tool\run.ps1 -InputFile '.\声顿产品报价表.xlsx'
```

默认输出到 `outputs`，文件名带运行时间。也可以指定新的输出路径和配置：

```powershell
.\catalog_tool\run.ps1 `
  -InputFile '.\声顿产品报价表.xlsx' `
  -OutputFile '.\outputs\声顿产品图册-新版.pptx' `
  -ConfigFile '.\catalog_tool\sendem.json'
```

输出路径须位于项目目录内，且不能与已有文件同名。输入表格需要一张工作表，包含“序号、产品名称、代理价、参考价B、功能特点、产品图片、包装图”这七个表头；表头可位于前 15 行，列顺序不限。图片须作为 Excel 嵌入图片锚定在对应产品行。

当前脚本使用本机 Codex 随附的 Node.js、Python、`@oai/artifact-tool` 和演示文稿校验器。`run.ps1` 会寻找这些依赖；如运行环境不同，可用 `-RuntimeRoot` 和 `-SkillDir` 指定位置。Python 运行时需具备 `openpyxl` 和 `python-pptx`。

## 图片与缺失值

- 有产品图时展示产品图；有另一张包装图时放在页眉缩略位置。
- 产品图缺失或被配置为占位图时，使用包装图作为主图。
- 两张图均缺失时采用纯文字布局。
- 缺失的价格或功能特点显示“未提供”；原表写“更新中”等文字时原样保留。
- `sendem.json` 中记录了本次表格“特价”占位图的 SHA-256。其他表格可编辑配置文件中的品牌、颜色和占位图哈希；不要把不同产品的相同图片自动认定为占位图。

图册的每页备注都记录来源工作表与行号。生成过程会输出逐页文字校验结果。`outputs`、临时提取图片和工作簿均排除在代码仓库之外。

## 测试

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s catalog_tool/tests -v
```
