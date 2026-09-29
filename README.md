# XLSX 转产品图册

把含产品资料和嵌入图片的 `.xlsx` 报价表转换成可编辑的 `.pptx` 图册。代码与使用说明见 [catalog_tool/README.md](catalog_tool/README.md)。

```powershell
.\catalog_tool\run.ps1 -InputFile '.\声顿产品报价表.xlsx'
```

默认只保留 `outputs/产品图册.pptx` 这一份输出；重新运行会在验证成功后替换它。

源工作簿、参考演示文稿、生成的图册与临时文件只保留在本机，不提交到代码仓库。
