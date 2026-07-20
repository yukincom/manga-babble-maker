# 台本テキスト記法（人が書く用）

| 項目 | 内容 |
|------|------|
| 状態 | **採用（仮仕様 v0）** |
| 機械用の正 | 変換後の `lines.json`（schema v1） |
| 目的 | コマ・話者・本文・形を、人が読み書きしやすい形で渡す |

テキストエディタの自動修正（先頭大文字化・全角など）が入ることがある。  
**パーサは寛容に正規化し、書くときは半角・小文字を推奨**する。

---

## 正式な例（カンマなし）

```text
page1
[１]

小雪 "やっと正月だー！" kumo

ナレーション "2025年" narration

[２]

小雪 "たまにはツイッター…" normal

小雪 "今はXだっけ" normal

[3]
小雪 "ん？" normal

小雪 "なんだこれ" normal

[4]
小雪 "見慣れぬアイコン・・・" normal

[枠外]
※ロゴは実際のものと異なります
```

---

## 文法

### ページ

```text
page1
page2
```

- `page` + 番号（半角・全角どちらも可 → 内部は半角数字）
- 1ファイル1ページでも、複数 `pageN` でも可（将来バッチ）

### コマ

```text
[1]
[２]
[3]
```

- 角括弧＋数字 = **読み順のコマ番号**（1始まり）
- 全角数字 `１` も可 → 正規化して `1`
- 検出の `frames` を読み順ソートしたときの **N 番目**に対応（マッピングはツール側）

### セリフ行

```text
話者 "本文" 形状
```

| 部品 | 必須 | 説明 |
|------|------|------|
| 話者 | 推奨 | キャラ名。`ナレーション` は地の文 |
| `"本文"` | **必須** | ダブルクォートで囲む |
| 形状 | 任意 | 省略時 `normal`。大文字小文字は無視 |

**カンマは使わない**（クォートと形状の区切りは空白）。

### 枠外

```text
[枠外]
※ロゴは実際のものと異なります
```

- 以降の行（または次の見出しまで）は `placement: page_margin`
- `※` 始まりは注釈として扱ってよい（枠なし表示は別 Issue）

### 空行

- 無視してよい（見やすさ用）

---

## 役割（tone）と形（shape）は別物

| 概念 | 何か | 例 |
|------|------|-----|
| **tone** | セリフの役割・雰囲気 | `normal` / `shout` / `thought` / `whisper` / `narration` |
| **shape** | 吹き出しの見た目 | `ellipse` / `jagged` / `cloud` / `dashed-ellipse` / `v-rect` |

- 台本末尾のトークンは主に **shape 用の短い名前**（下表）
- 話者 `ナレーション` や ※ は **tone=narration**
- tone 名（`shout` 等）を書いても可 → 既定 shape にマップ

JSON では:

```json
{ "text": "2025年", "speaker": "ナレーション", "type": "narration", "shape": "v-rect" }
```

台本例:

```text
ナレーション "2025年" narration
小雪 "ふざけるな！！" giza
小雪 "（……）" kumo
```

## 台本末尾トークン（少なめ・重複なし）

コード上の `_SHAPE_TOKENS` と一致させる。

| トークン | → shape | 既定 tone | いまの実装 |
|----------|---------|-----------|------------|
| `normal` | ellipse | normal | 楕円 |
| `giza` | jagged | shout | 固い控えめギザ |
| `kumo` / `cloud` | cloud | **normal** | 楽しい・明るい**発話**（テンプレ） |
| `thought` | ellipse | thought | **心の声**＝楕円＋丸連なり（雲にしない） |
| `whisper` | dashed-ellipse | whisper | 破線楕円 |
| `narration` | v-rect | narration | 縦長矩形 |

心の声に雲を使いたい場合だけ、明示的に別ルールを足す（既定では分離）。

tone 名を直接書いたとき（`shout` 等）も可。shape は既定:

| tone | 既定 shape |
|------|------------|
| normal | ellipse |
| shout | jagged |
| thought | cloud |
| whisper | dashed-ellipse |
| narration | v-rect |

未知トークン → ellipse + normal

---

## JSON への写像

```text
page1
[2]
小雪 "今はXだっけ" normal
```

↓

```json
{
  "schema_version": 1,
  "page": { "id": "page1" },
  "lines": [
    {
      "id": "l_…",
      "text": "今はXだっけ",
      "speaker": "小雪",
      "type": "normal",
      "panel_index": 2,
      "order": 1,
      "frame_id": null
    }
  ]
}
```

| 台本 | JSON |
|------|------|
| コマ内の上からの順 | `order`（コマ内 0,1,2… またはページ通し） |
| `[N]` | `panel_index: N` → 後で `frame_id` 解決 |
| `小雪` | `speaker` |
| `"…"` | `text` |
| `kumo` 等 | `type`（正規化名） |
| `[枠外]` 配下 | `meta.placement: "page_margin"`, `type: narration` 可 |

### コマ内配置（試し・予定）

同一 `panel_index` 内の `order` 順:

1. 右上  
2. 左上  
3. 左下  
（顔に被る場合はスキップ／ずらし）

---

## パーサがやる正規化

- 行頭・行末の空白除去  
- 全角数字 → 半角（`[１]` → panel 1）  
- 形状トークン → lower-case（`Kumo` → `kumo`）  
- 連続空行スキップ  
- `"本文"` の抽出（エスケープ `\"` は v1 で検討）

---

## 非対応（v0）

- 本文中の改行を1セリフに含める（必要なら後で `"""` ブロック）  
- カンマ区切り旧案（使わない）  
- 話者省略の通常セリフ（ナレ・枠外以外）

---

## 実装タスク（Issue 候補）

1. **仕様** … 本ドキュメント（済み）  
2. **パーサ** `script_text → lines.json`  
3. **panel_index → frame_id**（読み順ソート）  
4. **コマ内スロット配置** ①右上②左上③左下  

---

## モードB（ネーム先）との関係

台本の `話者` は、構造 JSON の `anchors[].speaker` と **同じ文字列**にすると、検出 face が無くても尻尾・近傍がそのアンカーに向く。

```text
小雪 "やっと　正月だー！" fun-cloud
  → lines[].speaker = "小雪"
  → anchors[] に speaker: "小雪" の頭 bbox
```

- 画像なし: `page.width/height` + `frames` + `anchors` + 本台本（または lines）で `place` 可  
- 例: `samples/structure/minimal.json`  
- 詳細 schema: [json-schema-draft.md](./json-schema-draft.md) §2b、計画 #35

---

## 変更ログ

| 日付 | 内容 |
|------|------|
| 2026-07-20 | v0。カンマなし・ユーザー提示の実例を正とする |
| 2026-07-20 | モードB: speaker ↔ anchors の対応を追記 |
