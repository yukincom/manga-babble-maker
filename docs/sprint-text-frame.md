# スプリント: 枠サイズ・字号・枠外・改行

| 項目 | 内容 |
|------|------|
| 日付 | 2026-07-20 |
| きっかけ | 余白対応後も枠位置が変わらず字だけ小さくなった／追加要件 |

## 要件（Issue）

| # | 内容 |
|---|------|
| [#18](https://github.com/yukincom/manga-babble-maker/issues/18) | フォント下限 **12px** |
| [#19](https://github.com/yukincom/manga-babble-maker/issues/19) | 枠外（page_margin）に **枠を付けない** |
| [#20](https://github.com/yukincom/manga-babble-maker/issues/20) | 改行・改列は **12文字以上**のときのみ |
| [#21](https://github.com/yukincom/manga-babble-maker/issues/21) | 枠サイズ＝文字量（空き最大で巨大化しない）≈ #1 |

## なぜ位置が変わらなかったか

`size_from_text` は **min 下限**にしか使われず、枠の half は距離変換の空き半径で決まっていた。  
→ 字を inset しても枠は巨大なまま → **字だけ小さく見える**。

## 修正方針

1. **#21** 空きは中心探しに使い、half は文字量サイズをそのまま使う  
2. **#18** `max(12, font_size)`  
3. **#19** `placement==page_margin` なら bubble レイヤに何も描かない  
4. **#20** `n < 12` は1列固定、`n >= 12` のみ折り返し検討  

## 実装順（コミットしやすい単位）

| 順 | 内容 | Issue |
|----|------|--------|
| 1 | place: prefer_text_size | #21 #1 |
| 2 | text: min 12px + wrap≥12 | #18 #20 |
| 3 | render: margin 枠なし | #19 |
| 4 | samples/real で目視 | — |

## 受け入れ

- [ ] 短文の吹き出しが明らかに小さくなる（位置も変わりうる）
- [ ] 文字が 12px 未満にならない
- [ ] ※ に白枠が付かない
- [ ] 11文字以下が勝手に複数列にならない
