# 実装マスタープラン（Issue 駆動・無駄なく）

| 項目 | 内容 |
|------|------|
| 日付 | 2026-07-20 |
| 方針 | **1 Issue（または密結合グループ）→ 実装 → テスト → commit → Issue 更新** |

---

## アーキテクチャ（固定）

```text
[任意] 小説シナリオ
        │  エージェント / LLM（core 外）
        ▼
台本テキスト (script-format.md)
        │  parse_script（決定的）
        ▼
lines.json  +  detections.json
        │  place（スロット＋文字量サイズ）
        ▼
layout.json  (text / tone / shape / bbox が正)
        │  render
        ▼
bubble.png（枠） text.png（プレビュー） manifest.json
```

- **編集の正** = JSON / 台本。PNG 文字はプレビューのみ  
- **tone** ≠ **shape**  
- 雲・自然破裂 template はユーザー素材待ち（#14 #16 は後）

---

## フェーズと Issue マッピング

### Phase A — 配置の正しさ（最優先・ユーザーが困っている）

| 順 | 内容 | Issues |
|----|------|--------|
| A1 | 枠サイズ＝文字量＋1字余白（空きで巨大化しない） | #1 #21 |
| A2 | 同一コマ: ①右上→②左上→③左下スロット（左右分け） | 新規相当 #2/#5 の具体化 |
| A3 | panel_index / frame_id 解決（読み順コマ、顔なしコマ可） | #5 #17 一部 |
| A4 | 被り回避（占有＋スロットずらし） | A2 内 |

### Phase B — 文字プレビュー（読める）

| 順 | 内容 | Issues |
|----|------|--------|
| B1 | フォント下限 12px | #18 |
| B2 | 12文字未満は1列・密な字送り（バラバラ禁止） | #20 #13 一部 #6 #10 |
| B3 | 枠外は枠なし | #19 |

### Phase C — 入力

| 順 | 内容 | Issues |
|----|------|--------|
| C1 | 台本パーサ script → lines.json | #17 |
| C2 | CLI parse-script | #17 |

### Phase D — 後回し（素材・仕上げ）

| 内容 | Issues |
|------|--------|
| 雲 template / 自然破裂 | #14 #16 #3 後半 |
| Skill 文書 | #9 |
| 禁則フル | #11 |
| lang | #12 |
| 尻尾の更なる短縮 | #4 一部済み |

---

## このセッションで完了させる範囲

**Phase A + B + C1** をコードに入れる。  
D は素材待ちのため実装しない。

コミット単位:

1. `feat(place): text-sized bubbles + panel slots`  
2. `feat(text): pack glyphs, min 12px, wrap>=12`  
3. `feat(render): no frame for page_margin notes`  
4. `feat(script): parse structured script format`  
5. `chore: samples + docs + issue notes`
