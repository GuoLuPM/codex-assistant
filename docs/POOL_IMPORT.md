# Codex 入库与推荐标签合同

由 [pool 流程](../catalog_tool/POOL_WORKFLOW.md) 绑定，首次非 XLSX 记录或添加标签时读取。所有 JSON 示例均为合成示例；实际 ref / 原文必须来自该文件的 `inspect`。

## 原生证据 → 单品/批次

`add` 返回 file_id。`inspect --file ID` 分页返回 `id/kind/text/locator/page`；引用的是条目 id，不是页码或猜测 ID。长文本用 `--ref ID --max-chars 2000 --text-offset 2000` 续读。一个 PDF 页/PPT 页可能有多款商品，不把整页一律当成单品。

将如下数组写到私有 `.local.json`，`import --file 文件ID --records 路径`：

```json
[
  {
    "key": "page1-cup-A",
    "fields": {
      "name": {"ref": "p1:text1", "quote": "便携水杯"},
      "model": {"ref": "p1:text2", "quote": "C-20"}
    },
    "prices": {
      "retail_price": {
        "label": {"ref": "p1:text3", "quote": "零售价"},
        "value": {"ref": "p1:text3", "quote": "120元"}
      }
    },
    "features": [{"ref": "p1:text4", "quote": "附礼盒"}],
    "images": ["p1:image1"]
  }
]
```

- `key` 是你为此来源单品确定的稳定定位，不随导入次数/名称润色改变。同 key 原值重试跳过；同 key 不同内容显式冲突，不能换 key 绕过冲突制造重复。
- `fields.name` 必需；其余支持 model/variant/category/brand/supplier。每个事实都是 `{ref,quote?}`，quote 必须逐字出现在那条原文，省略 quote 表示整条原文。不能自行另写 value。
- `prices` 角色如 retail_price / supply_price / reference_price，各角色的 label 和 value 均引用原文。保留币种、单位、区间等原表示；复杂字符串不会参加数值预算。角色含义由明确上下文判断，无法判断时别混成已知价格口径。
- `features` 为原文引用数组；`images` 仅用同文件真实图片证据 id，缺图省略。整页预览只是来源图，不等于已经裁切成商品图，多商品整页不要当单品主图。
- 仅处理部分商品时状态为 partial，不能说整文件已完成。每批 1..100 条，允许只有一条；不同文件间不会靠相似名称自动合并。
- XLSX 优先既有坐标映射，可覆盖整文件，并保留合并、变体和原图关系；本合同不是第二套猜表头规则。

## 视觉转录

原生文本不足时用 Codex 看图（PDF 先 `render --file ID --page 页码`）。将能逐字辨认的文字写私有文本，执行 `observe --file ID --image-ref 图片ID --text-file 路径 --reviewer codex`。返回的 ref 可以引用，但记录会标注视觉转录；程序不能证明图片中文字被读对，价格疑点必须复查/留空。不能把未查看的图片伪称已复核。

## 场合、对象、用途等标签

先 `facets --kind occasion` 查询已用词，尽量复用同义概念，避免“春节/过年/新年”被无意义拆散。没有预设行业/节日分支；kind 可扩展（例如 occasion、audience、usage、style、material）。

```json
[
  {
    "id": "p_实际ID",
    "kind": "occasion",
    "value": "新年",
    "origin": "inferred",
    "reason": "原文写春节赠礼，推荐用于新年送礼场景",
    "evidence": "适合春节赠礼"
  }
]
```

通过 `annotate --records 路径.local.json` 写入。evidence 必须逐字来自该产品已保存事实；不能从另一款借证据。`source` 还要求标签词出现在证据里，否则用 `inferred` 并写判断理由。推荐标签不补造商品参数、认证或效果。

检索组合：`search --price-field retail_price --max-price 150 --category 杯壶 --tag occasion:新年 --tag audience:同事`。多个 tag 默认全部满足，`--tag-mode any` 任一满足，`--tag-origin source` 仅采信来源明示。无标签的商品不自动排除为“不适合”。多路补查、资料整理及跨来源同款报价分组遵循 [资料与检索合同](POOL_RETRIEVAL.md)：保留来源记录，只有明确复核的同款关系可折叠显示。
