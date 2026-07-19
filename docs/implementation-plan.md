# 実装計画

| 項目 | 内容 |
|------|------|
| 文書 | 実装計画（フェーズ分割・モジュール・受け入れ条件） |
| 方針の正 | リポジトリルート [`Agent.md`](../Agent.md) |
| JSON 草案 | [`json-schema-draft.md`](./json-schema-draft.md) |
| 更新日 | 2026-07-19 |
| 前提 | MCP + エージェント（ヘルメス等）利用。core → CLI → MCP。既定ローカル・黙って外部送信しない |

本計画は **コードを書く順序と完了条件** を固定するためのもの。方針が変わったら先に `Agent.md`、次に本ドキュメントを更新する。

---

## 1. ゴール（何ができたら成功か）

### プロダクト最小成功（P1 完了時）

1. 完成したマンガ絵 + セリフ JSON を渡す
2. （自動または手渡し）body/face/frame 検出
3. 空白とキャラを避けて吹き出し位置を決める
4. セリフから tone を決める（規則）
5. 出力:
   - `bubble` レイヤ PNG（枠・尻尾のみ）
   - `text` レイヤ PNG（文字のみ・見た目用）
   - `layout.json`（**text / tone / bbox 必須**）
   - art は入力を保持（上書きしない）
6. 上記を **非対話 CLI** で実行でき、stdout にマニフェスト JSON
7. **オフライン**で一巡できる（モデルはローカル配置済み）

### エージェント成功（P2 完了時）

- 同じ core を **MCP tools** から呼べる
- ヘルメス等から `detect` → `place` → `render` を段階実行できる

---

## 2. 現状（2026-07-19）

### 済み

| 項目 | 状態 |
|------|------|
| 方針文書 `Agent.md` | 合意済み |
| git / `.gitignore` / `requirements.txt` / `.venv` | 済み |
| ONNX モデル配置 `models/rtdetrv4-x-manga109s_v2/model.onnx` | 済み（git 外） |
| 配置 MVP `bubble_placement_mvp.py` | 幾何 + 重なり回避あり |
| SVG 形状 `bubble_vector_generator.py` | 参考実装（本線はラスタへ移植） |
| デモ `demo_render.py` | Claude パス固定・要置換 |

### 未着手（本計画の対象）

- JSON スキーマ実装・サンプル
- パッケージ構成（core / cli）
- tone 規則
- ラスタ render + レイヤ分離
- RT-DETR 推論ラッパ
- 話者マッピング
- CLI / MCP
- テスト

---

## 3. 目標アーキテクチャ

```
manga_babble/                 # インストール可能なパッケージ
  __init__.py
  schema.py                   # schema_version, load/validate の薄い層
  detect/
    rtdetr_onnx.py            # ONNX 推論
  tone/
    resolve.py                # explicit → rule → default
  place/
    candidates.py             # 既存 MVP を移植・拡張（文字量・話者）
  render/
    bubble_raster.py          # 枠・尻尾（ラスタ）
    text_raster.py            # 文字プレビュー（ラスタ）
    compose.py                # 任意プレビュー合成
  pipeline.py                 # detect / place / render / run
  export.py                   # layout.json / manifest 書き出し

cli.py  or  manga_babble/cli.py
  detect | place | render | run

mcp_server.py                 # P2: core の薄いラッパ
```

ルートに残すレガシー:

- `bubble_placement_mvp.py` / `bubble_vector_generator.py` … 移植後に `legacy/` へ移すか削除（計画フェーズ D で判断）
- `demo_render.py` … 新 CLI に置換

### データ流

```
image.png + lines.json
        │
        ▼ detect
 detections.json
        │
        ▼ place  (+ lines)
 layout.json          ← text/tone/bbox の正
        │
        ▼ render
 bubble.png | text.png | manifest.json | (preview.png)
```

役割を混ぜない:

| モジュール | 責務 |
|------------|------|
| detect | 画素 → bbox |
| tone | 文字列 → tone |
| place | bbox + lines → layout |
| render | layout → 画像レイヤ |
| export | パス一覧・JSON 永続化 |
| cli / mcp | I/O と引数。ロジックなし |

---

## 4. フェーズ計画

全体の依存関係:

```
A 土台 JSON・パッケージ
    → B tone + place 拡張 + ラスタ render（固定 detections で一巡）
        → C detect ONNX 接続
            → D CLI 仕上げ・デモ置換・テスト
                → E MCP
                    → F マンガらしさ・表現（P2/P3）
```

---

### フェーズ A — 土台（P0 残り）

**目的:** 契約とディレクトリを固定し、以降の実装が迷わないようにする。

| # | タスク | 詳細 | 受け入れ条件 |
|---|--------|------|----------------|
| A1 | JSON 草案の確定 | `docs/json-schema-draft.md` を実装の正とする。必要なら軽微修正 | フィールド一覧が place/render に足りる |
| A2 | サンプルデータ | `samples/` にダミー detections + lines + 説明 | 画像なしでも place を後で回せる |
| A3 | パッケージ骨格 | `manga_babble/` 作成、空モジュール + `pipeline` スタブ | `python -c "import manga_babble"` |
| A4 | schema ヘルパ | load/save JSON、`schema_version` チェック | 不正 JSON で明確なエラー |
| A5 | 出力ディレクトリ規約 | 例: `out/<stem>_bubble.png` 等 | README または docs に 1 表 |

**成果物:** `manga_babble/` 骨格、`samples/`、docs 確定。  
**まだやらない:** 本格描画、ONNX 推論。

---

### フェーズ B — 最小一巡（固定検出 + セリフ）

**目的:** 「セリフ → tone → 配置 → レイヤ出力」を **検出なし**で通す。

| # | タスク | 詳細 | 受け入れ条件 |
|---|--------|------|----------------|
| B1 | tone 解決 | `type` 明示 → 規則（`！`/`（）`/…）→ `normal`。`tone_source` を meta に | 単体テスト数ケース |
| B2 | 配置の移植 | `compute_bubble_candidates` を `manga_babble.place` へ | 既存ダミー bbox で同等候補 |
| B3 | 文字量 → サイズ | 文字数から希望 half_w/h の下限・上限。縦書きは「仮の文字数→高さ」で可 | 長いセリフほど大きくなりうる |
| B4 | 話者マッピング（最小） | `speaker` 一致 or 未指定時は face を順繰り/最近傍 | layout に `speaker_face_bbox` |
| B5 | ラスタ bubble | tone 別の枠・尻尾を Pillow/cv2 で描画。**文字を含めない** | 透明 PNG、白塗り+黒線程度で可 |
| B6 | ラスタ text | bubble_bbox 内に文字列。縦書きは簡易（1 列）で可 | bubble と別 PNG |
| B7 | export | `layout.json` + manifest（files + bubbles の text/tone/bbox） | JSON のみで後段が読める |
| B8 | 任意 preview | art の上に bubble+text を合成 | 無くても B 完了可 |
| B9 | pipeline.place / render | 関数 API | サンプル 1 本でファイル生成 |

**成果物:** `samples` から `out/*_bubble.png`, `*_text.png`, `*_layout.json`。  
**依存:** フェーズ A。  
**既存 SVG:** 形状パラメータの参考のみ。本線出力に使わない。

---

### フェーズ C — 検出接続（RT-DETR ONNX）

**目的:** 画像パスだけで detections を埋める。

| # | タスク | 詳細 | 受け入れ条件 |
|---|--------|------|----------------|
| C1 | 推論ラッパ | カード準拠: 1280 resize、`[0,1]`、CPU provider。conf 閾値 | ダミー or 実ページで labels 出力 |
| C2 | クラス分け | 0 body / 1 text / 2 frame / 3 face → detections JSON | schema 準拠 |
| C3 | frame 紐付け（簡易） | face/body を含む frame を heuristically 付与 | frame_id が入る（荒くて可） |
| C4 | occupied に text | 既存 text 検出を占有に足す（任意だが推奨） | 既存吹き出しに被りにくい |
| C5 | pipeline.detect / run | image+lines → 全自動 | offline で E2E |
| C6 | モデルパス | 既定 `models/rtdetrv4-x-manga109s_v2/model.onnx`、引数で上書き | 欠落時は分かりやすいエラー |

**成果物:** `manga_babble detect` 相当の API + 実画像 1 枚での目視。  
**注意:** 原稿サンプルを git に載せない（`.gitignore` の `outputs/` やユーザーローカル）。

---

### フェーズ D — CLI と品質（P1 仕上げ）

**目的:** 人・エージェントが shell から同じ契約で使える。

| # | タスク | 詳細 | 受け入れ条件 |
|---|--------|------|----------------|
| D1 | CLI | `detect` / `place` / `render` / `run`。非対話。パス明示 | `--help` あり |
| D2 | stdout 規約 | 成功時マニフェスト JSON のみ。ログは stderr | パイプで jq 可能 |
| D3 | exit code | 0 ok / 非 0 error + errors[] | エージェントが分岐可能 |
| D4 | demo 置換 | 旧 `demo_render.py` を CLI 呼び出し or 削除 | ローカルパス問題解消 |
| D5 | レガシー整理 | MVP を package へ寄せ、ルートは薄く | import 経路が一本 |
| D6 | テスト | tone / place 幾何 / schema の pytest 最低限 | `pytest` 緑 |
| D7 | 短い README | セットアップ・モデル DL・CLI 例 | 新規クローンで再現手順が読める |

**成果物:** P1 完了チェックリストをすべて満たす。

---

### フェーズ E — MCP（P2 前半）

**目的:** ヘルメス等から tool call。

| # | タスク | 詳細 | 受け入れ条件 |
|---|--------|------|----------------|
| E1 | MCP サーバ | tools = detect / place / render / run。core 呼び出しのみ | ローカルで tool 一覧 |
| E2 | 入出力 | スキーマは CLI と同じ JSON | 二重ロジックなし |
| E3 | 設定例 | エージェント側 MCP 設定のサンプル（docs） | コピペで繋げる |
| E4 | 運用一文 | 「本ツールは勝手にアップロードしない。クラウドはエージェント設定次第」 | docs に記載 |

**成果物:** MCP 経由で P1 と同じ一巡。

---

### フェーズ F — マンガらしさ・表現（P2/P3）

優先度は利用しながら上げる。**E より前に無理に入れない。**

| # | タスク | フェーズ感 |
|---|--------|------------|
| F1 | 読み順・右上優先のスコア | P2 |
| F2 | 作品傾向プリセット（余白・優先領域） | P2 |
| F3 | 複数吹き出しの間隔・衝突の改善 | P2 |
| F4 | 縦書き・折り返し・マージン改善 | P2 |
| F5 | 追加 tone（pop / flash 系） | P3 |
| F6 | バッチ・複数ページ | P3 |
| F7 | CSP 手順メモ（3 レイヤ + JSON） | P3 |
| F8 | 既存吹き出し検出（ogkalu）オプション | 条件付き |
| F9 | 編集可能テキスト（SVG text 等） | 需要後 |

---

## 5. 実装順序（推奨スプリント）

現実的な切り方（1 スプリント ≒ まとまった PR 単位）:

| 順 | 内容 | 完了の見え方 |
|----|------|----------------|
| **S0** | A（骨格 + samples + schema） | import と JSON サンプル |
| **S1** | B1–B4（tone + place） | layout.json が正しく出る |
| **S2** | B5–B9（render + pipeline） | 3 系統ファイルが揃う |
| **S3** | C（ONNX detect + run） | 画像 1 枚 E2E offline |
| **S4** | D（CLI + test + README） | **P1 完了** |
| **S5** | E（MCP） | エージェント接続 |
| **S6+** | F（品質・表現） | 継続改善 |

---

## 6. CLI インターフェース案

```bash
# 検出のみ
python -m manga_babble detect --image page.png --out out/detections.json

# 配置（検出結果 + セリフ）
python -m manga_babble place \
  --detections out/detections.json \
  --lines lines.json \
  --out out/layout.json

# 描画
python -m manga_babble render \
  --layout out/layout.json \
  --out-dir out/

# 一括
python -m manga_babble run \
  --image page.png \
  --lines lines.json \
  --out-dir out/ \
  --model models/rtdetrv4-x-manga109s_v2/model.onnx
```

共通:

- 失敗時 stderr にメッセージ、stdout に error マニフェスト（または空 + exit≠0）
- `--seed` で形状再現

---

## 7. MCP tools 案（フェーズ E）

| tool | 引数 | 戻り |
|------|------|------|
| `detect_page` | `image_path`, `model_path?`, `conf_threshold?` | detections JSON or path |
| `place_bubbles` | `detections` (path or object), `lines` (path or object) | layout JSON or path |
| `render_layers` | `layout` (path or object), `out_dir` | manifest |
| `run_pipeline` | `image_path`, `lines`, `out_dir`, … | manifest |

CLI と 1:1。ロジックは `manga_babble.pipeline` のみ。

---

## 8. テスト方針

| 種類 | 対象 | 時期 |
|------|------|------|
| 単体 | tone 規則、bbox クリップ、schema | B〜D |
| 回帰 | 固定 detections + lines → layout の bbox おおまか一致 | B |
| 結合 | render が透明 PNG を吐く、JSON に text がある | B |
| 手動 | 実ページ 1 枚の目視（git 外画像） | C |
| MCP | tool が manifest を返す | E |

自動テストに **大きな ONNX や実原稿を必須にしない**（CI では mock detections）。

---

## 9. リスクと緩和

| リスク | 緩和 |
|--------|------|
| 配置がマンガ的に不自然 | まず幾何で通す。F1–F3 でスコア改善 |
| 縦書きレイアウトが貧弱 | P1 は「読める仮」。F4 で改善 |
| ONNX が重い・遅い | CPU 既定。後で GPU provider オプション |
| 話者付けが間違う | layout を人間/エージェントが直して re-render 可能にする |
| SVG レガシーと二重管理 | フェーズ B でラスタ本線を確定し、SVG は参考扱いを維持 |
| スコープ膨張（写植完全、CSP ネイティブ） | P3 まで触らない。JSON + PNG レイヤで止める |

---

## 10. 明示的にやらないこと（本計画の範囲外）

- セリフ本文の生成
- 枠のベクター必須化
- transformers 検出
- クラウド API の本線組み込み / 秘匿 UX の厚作り
- ComfyUI 必須化
- GUI
- 商用級ルビ・禁則

---

## 11. 完了チェックリスト

### P0（ほぼ完了 + 本計画の A）

- [x] Agent.md 方針
- [x] git / gitignore / requirements / venv
- [x] モデル DL 手順とローカル配置
- [x] フェーズ A（JSON・samples・package 骨格）

### P1

- [x] tone 規則
- [x] place（文字量・話者最小）
- [x] raster bubble / text 分離
- [x] layout.json に text/tone/bbox
- [x] detect ONNX
- [x] CLI 非対話 + manifest
- [x] offline E2E（固定 detections + ローカル ONNX ロード）
- [x] 最低限テスト + README

### P2

- [x] MCP（薄いラッパ）
- [ ] エージェントからの接続確認（利用側）
- [ ] （任意開始）読み順・作品傾向

---

## 12. 次のアクション（実装開始時）

1. **フェーズ A を実装する**（本ドキュメントと `json-schema-draft.md` に従う）
2. サンプル `samples/demo_lines.json` + `samples/demo_detections.json` を追加
3. `manga_babble/` パッケージを切り、既存 placement を移し始める

実装エージェントは、各フェーズの受け入れ条件を満たしたら次へ進む。方針と矛盾する変更は先に `Agent.md` と本計画を更新する。
