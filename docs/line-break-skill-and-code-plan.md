# 改行・文字入れ：Skill とコードの実装計画

| 項目 | 内容 |
|------|------|
| 日付 | 2026-07-20 |
| 前提 | 改行は **汎用パイプライン ＋ パラメータ**。作品名・固定キャラ名は **ハードコードしない** |
| 関連 Issue | #23（中心起点）、#24（改行ルール）、#13（語中で切らない）、#9（Skill） |
| コミット | **ユーザー指示があるまで行わない**（運用に従う） |
| コード実装 | 2026-07-20: C1–C6 相当。接続語仮辞書は廃止。**本番改行はエージェントが `/` や `　` を挿入** |
| 改行の本命 | Skill → エージェント（目安 7B–14B 級でも可）が区切り記号を付与。コードは記号を遵守 |

---

## 1. ゴール

| 層 | ゴール |
|----|--------|
| **Skill** | エージェントが台本／JSON を書く・直すとき、切れ目とパラメータを **正しく明示**できる |
| **コード** | 明示された切れ目を **決定的に** 描画する。未指定時のみ薄いフォールバック |

編集者品質の完全自動は目指さない。  
目指すのは:

1. 台本の `　` / 改行 / 構造を最優先で守る  
2. 吹き出し中心に文字塊を置く  
3. プロファイル（作風・テンション・声の粗さ）でフォールバックだけ変える  

---

## 2. やってはいけないこと

- 特定作品名をコードや Skill の分岐条件に書く  
- 特定の固定キャラ名リストをリポジトリに埋め込む  
- 「14文字→5行」など **一枚岩の字数表だけ**で改行を決める  
- core がクラウド LLM を必須にする  

キャラ差・作品差は **データ（プロファイル JSON）や台本メタ**で渡す。

---

## 3. 概念モデル（共通・汎用）

### 3.1 改行パイプライン

```text
【本番・推奨】
  エージェント（Skill）が本文に区切り記号を入れる
    - 全角スペース「　」
    - スラッシュ「/」（ASCII、エディタでも扱いやすい）
    - または改行

【コード】
  ① 上記明示区切りだけを信じて split（決定的）
  ② 記号が無いとき: ほぼ 1 塊。構造ヒントは最小
       （ひらがな/漢字→カタカナ境、これ/それ 程度。接続語辞書は持たない）
  ③ profile（genre/tension/voice）は長さセーフティの目安のみ
  ④ 枠外注釈: 12 字未満は改行しない

接続語・文節の「無限リスト」はコードに載せない。
見分けは Skill を渡した LLM（14B 前後でも十分なタスク想定）に任せる。
```

### 3.2 パラメータ（名前は作品非依存）

| キー | 型 | 意味 |
|------|-----|------|
| `genre` | enum | `default` / `action` / `read` / `mixed` …（内部ラベル。作品名ではない） |
| `tension` | enum | `low` / `mid` / `high` |
| `voice` | enum | `dense`（改行多め）/ `normal` / `sparse`（改行少なめ） |
| `allow_midword_split` | bool | 高テンション口語用。default false |
| `chunk_max_chars` | int | 1チャンク目安上限 |
| `target_lines_soft` | int | ソフトな目標行数 |

**導出（コード内の表・ハードコード可なのは enum の意味だけ）:**

```text
effective_chunk_max =
  base(genre) × tension_factor × voice_factor

allow_midword_split =
  genre in {action, mixed} AND tension == high
  （または明示フラグ）
```

キャラ名は出さない。  
「この話者は dense」は **入力データの `speakers` マップ**で渡す。

```json
{
  "options": {
    "genre": "mixed",
    "tension": "mid",
    "speakers": {
      "A": { "voice": "dense" },
      "B": { "voice": "sparse" }
    }
  },
  "lines": [
    { "speaker": "A", "text": "…", "type": "normal" }
  ]
}
```

話者文字列は作品依存でよいが、**リポジトリのコード定数には書かない**。

### 3.3 レイアウト（改行と独立・コード必須）

- 文字塊の幾何中心 ≒ 吹き出し中心（#23）  
- 内側余白 ≒ 1 文字  
- フォント下限 12px  
- 縦書き: 列は右→左、字は上→下  
- 枠外注釈: 枠なし  

---

## 4. Skill 計画

### 4.1 成果物

| パス案 | 内容 |
|--------|------|
| `.grok/skills/manga-script-linebreaks/SKILL.md` または repo 内 `skills/manga-babble-script/SKILL.md` | エージェント手順 |
| （任意）`docs/line-break-model.md` | 人間向けの短い理論（作品名なし） |

Skill の置き場はユーザー環境に合わせて決める。  
**リポジトリに置く場合も作品名・実在キャラ名の例は一般名（話者A、街の子）に留める。**

### 4.2 Skill がやること

1. **入力の種類を判別**  
   - 構造化台本（page / [n] / 話者 "本文" shape）  
   - 小説風 → 構造化台本へ変換  
2. **改行の入れ方**  
   - 意味の切れ目に全角スペース `　` を入れる  
   - 明示が最優先だとコードが再現すること  
3. **パラメータの付け方**  
   - `genre` / `tension` を options に  
   - 話者ごとの `voice` を speakers マップに（名前は入力から取る。Skill が固定リストを持たない）  
4. **やってはいけないこと**  
   - 単語の途中で無意味に切る  
   - コードに無い shape 名を量産する  
   - 吹き出し PNG を編集可能テキストだと思わない  

### 4.3 Skill がやらないこと

- 座標計算・検出・描画  
- 形態素解析ライブラリの実行（必要ならコード側）  
- 特定作品のネタ・固有設定の内蔵  

### 4.4 Skill 実装タスク（順）

| # | タスク | 完了条件 |
|---|--------|----------|
| S1 | SKILL.md 骨子（入力→台本→JSON、改行パイプライン①〜④） | エージェントが読める |
| S2 | `　` の打ち方・優先順位・悪い例/良い例（一般名のみ） | 例が作品非依存 |
| S3 | genre / tension / voice の選び方チェックリスト | 名前付き enum のみ |
| S4 | 小説→構造化の変換テンプレ | 出力が script-format 準拠 |
| S5 | manga-babble CLI への渡し方（parse-script / run） | コピペ手順あり |

---

## 5. コード計画

### 5.1 モジュール案

```text
manga_babble/
  text/
    breaks.py      # 明示区切り + フォールバック分割 → list[str] chunks
    profile.py     # genre/tension/voice → 数値パラメータ
    layout_text.py # 中心起点で chunk を縦組み配置（text_raster から分離可）
  render/
    text_raster.py # layout_text を呼ぶ or 統合
```

既存 `text_raster.py` を肥大化させず、**分割ロジックと描画を分離**する。

### 5.2 データ契約

**入力（lines 要素）:**

```json
{
  "text": "明示　区切りあり",
  "speaker": "任意の話者名",
  "type": "normal",
  "meta": {
    "voice": "dense"
  }
}
```

**ページ options:**

```json
{
  "options": {
    "genre": "default",
    "tension": "mid",
    "speakers": {
      "任意の話者名": { "voice": "sparse" }
    }
  }
}
```

優先: `line.meta.voice` > `options.speakers[speaker].voice` > `normal`

**出力:** 従来どおり layout の `text` は **結合前の本文を保持**（編集の正）。  
チャンクは描画時に計算するか、`meta.chunks` に保存（再描画用・任意）。

### 5.3 コード実装タスク（順）

| # | タスク | Issue | 完了条件 |
|---|--------|-------|----------|
| C1 | `profile.py`: enum → chunk_max 等 | #24 一部 | 表が作品名なし |
| C2 | `breaks.py`: 明示 `　`/`\n` 分割 | #24 | スペース位置で確定分割 |
| C3 | フォールバック: 助詞終わり等の簡易境界 | #24 #13 | テストで一般文 |
| C4 | midword は flag 時のみ | #24 | default off |
| C5 | 中心起点レイアウト | #23 | 塊の中心 = bubble 中心 |
| C6 | 12px・1字余白維持 | #18 済と整合 | 回帰テスト |
| C7 | CLI 変更なしで render 経由で動く | — | real サンプル目視 |
| C8 | 単体テスト（一般文・スペース付き・voice 差） | #23 #24 | pytest 緑 |

### 5.4 コードに書かないもの

- 固有名詞辞書（作品キャラ）  
- 作品タイトル分岐  
- 「14文字→5行」固定表を唯一のロジックにすること  

字数目安は **profile から出る chunk_max** の結果として現れる。

---

## 6. Skill とコードのインターフェース

```text
エージェント（Skill）
  1. ユーザ原稿・小説を読む
  2. genre / tension を推定して options に書く
  3. 話者ごとに voice を options.speakers に書く（入力上の名前をキーにする）
  4. 本文に　で切れ目を入れる
  5. script または lines.json を出力
        │
        ▼
manga_babble parse-script / place / render
  1. breaks: 明示区切りを適用
  2. 不足分だけ profile 付きフォールバック
  3. 中心起点で描画
```

**契約テスト:**  
「本文中の `　` の数 + 1 ≒ 描画チャンク数」（フォールバックが走らない場合）。

---

## 7. フェーズとコミット案（指示後に実行）

| Phase | 内容 | 成果物 |
|-------|------|--------|
| **P0** | 本計画のレビュー | docs のみ |
| **P1** | Skill S1–S3 | SKILL.md |
| **P2** | コード C1–C2–C5（明示区切り＋中心） | breaks + layout_text |
| **P3** | コード C3–C4–C6（フォールバック＋voice） | profile 連動 |
| **P4** | Skill S4–S5 + 結合テスト | 小説→script→render 手順 |
| **P5** | Issue #23 #24 を Close、#20 を吸収 Close | gh |

コミット分割例（**ユーザーが commit 指示してから**）:

1. `docs: line-break skill/code plan (no work titles)`  
2. `feat(text): explicit break parsing and center layout`  
3. `feat(text): profile-based fallback breaks`  
4. `chore: skill for script linebreaks`  

---

## 8. テスト方針（一般化）

| テスト | 内容 |
|--------|------|
| 明示区切り | `"ああ　いい"` → 2 chunks |
| 中心 | 塊の bbox 中心が bubble 中心の近傍 |
| voice | 同じ本文・スペースなしで dense の方が chunk 数 ≥ sparse（フォールバック時） |
| midword | default では漢字連続語を途中分割しない |
| 回帰 | 既存 place/slots/parser テストが緑 |

作品固有セリフはテストに使わない。  
合成文: `名前A　行け` / `〜を　するんだ` 等。

---

## 9. 成功の定義

- エージェントが Skill だけで「切れ目付き台本」を出せる  
- コードが切れ目を守り、中心に文字を置ける  
- リポジトリに **作品名・固定キャラ名が無い**  
- 作風差は `genre` / `tension` / `voice` で説明できる  

---

## 10. 次のアクション

1. ユーザーが本計画を OK するか確認  
2. OK なら **P1 Skill** か **P2 コード（#23+#24 の明示区切り＋中心）** のどちらから行くか指定  
3. **commit は別指示まで禁止**  
