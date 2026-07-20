# 入出力 JSON スキーマ草案

`schema_version: 1` 時点の契約案。実装時に必要ならマイナー修正し、破壊的変更は `schema_version` を上げる。

方針: エージェント（MCP/CLI）・人が同じ JSON を読み書きできること。画像本体はパス参照（base64 必須にしない）。

---

## 共通

```json
{
  "schema_version": 1
}
```

座標はすべて **元画像ピクセル、xyxy（左上 x1,y1 / 右下 x2,y2）、float 可**。  
原点は画像左上。単位 px。

---

## 1. 入力: セリフリスト（`lines`）

エージェントまたは人が用意する台本。

```json
{
  "schema_version": 1,
  "page": {
    "image_path": "path/to/page.png",
    "width": 1000,
    "height": 1400
  },
  "lines": [
    {
      "id": "l1",
      "text": "なんだと！？",
      "order": 0,
      "speaker": "char_a",
      "type": null,
      "frame_id": null
    },
    {
      "id": "l2",
      "text": "（……そうか）",
      "order": 1,
      "speaker": null,
      "type": "thought",
      "frame_id": null
    }
  ],
  "options": {
    "style": "default",
    "seed": 0,
    "conf_threshold": 0.5
  }
}
```

| フィールド | 必須 | 説明 |
|------------|------|------|
| `page.image_path` | detect 時は必須 | 原稿画像 |
| `page.width/height` | 任意 | 省略時は画像から取得 |
| `lines[].id` | 推奨 | 安定 ID。省略時は生成可 |
| `lines[].text` | **必須** | セリフ本文 |
| `lines[].order` | 推奨 | 読み順（小さいほど先） |
| `lines[].speaker` | 任意 | 話者ラベル。face 紐付けに使う |
| `lines[].type` | 任意 | 明示 tone。null なら規則解決 |
| `lines[].frame_id` | 任意 | コマ指定。省略時は自動 |
| `options.style` | 任意 | 作品傾向プリセット ID（P2） |
| `options.seed` | 任意 | 形状の再現用 |
| `options.conf_threshold` | 任意 | 検出閾値 |

---

## 2. 中間: 検出結果（`detections`）

`detect` の出力。手書き JSON でも可（E2E 前のテスト用）。

```json
{
  "schema_version": 1,
  "page": {
    "image_path": "path/to/page.png",
    "width": 1000,
    "height": 1400
  },
  "detections": {
    "frames": [
      { "id": "f0", "bbox": [10, 10, 980, 700], "score": 0.95 }
    ],
    "bodies": [
      { "id": "b0", "bbox": [100, 600, 400, 1400], "score": 0.9, "frame_id": "f0" }
    ],
    "faces": [
      { "id": "face0", "bbox": [150, 600, 300, 750], "score": 0.88, "frame_id": "f0", "speaker": "char_a" }
    ],
    "texts": [
      { "id": "t0", "bbox": [500, 100, 700, 200], "score": 0.8, "frame_id": "f0" }
    ]
  },
  "model": {
    "name": "rtdetrv4-x-manga109s_v2",
    "path": "models/rtdetrv4-x-manga109s_v2/model.onnx",
    "conf_threshold": 0.5
  }
}
```

| クラス | 用途 |
|--------|------|
| `frames` | コマ境界。配置の枠・壁 |
| `bodies` | 占有領域（隠さない） |
| `faces` | 占有 + 尻尾の狙い先 + 話者 |
| `texts` | 既存台詞領域。占有に足すとよい（任意・P1 後半） |

`faces[].speaker` は検出では通常出ない。後段マッピングまたは人手で付与。

### 2b. 話者アンカー（`anchors`）— モードB / ネーム先

検出 face と同じ役割の矩形。**頭・立ち位置・ラベル位置**など、尻尾 aim と HARD 占有に使う。  
完成絵検出の代わり、または併用（place は `faces ∪ anchors` を同一 AimRef に正規化）。

`detections.anchors` でも、構造 JSON の **トップレベル `anchors`** でも可（`place` はどちらも読む）。

```json
{
  "schema_version": 1,
  "page": { "width": 1000, "height": 800 },
  "frames": [
    { "id": "f0", "bbox": [40, 40, 960, 760] }
  ],
  "anchors": [
    {
      "id": "a_right",
      "bbox": [680, 220, 820, 380],
      "speaker": "話者A",
      "frame_id": "f0",
      "kind": "head"
    },
    {
      "id": "a_left",
      "bbox": [160, 240, 300, 400],
      "speaker": "話者B",
      "frame_id": "f0",
      "kind": "head"
    }
  ],
  "lines": [
    {
      "id": "l0",
      "text": "右から話すよ",
      "speaker": "話者A",
      "panel_index": 1,
      "type": "normal",
      "order": 0
    }
  ]
}
```

| フィールド | 必須 | 説明 |
|------------|------|------|
| `anchors[].id` | 推奨 | `lines[].anchor_id` / `face_id` から参照可 |
| `anchors[].bbox` | **必須** | 頭または立ち位置の xyxy |
| `anchors[].speaker` | 任意 | `lines[].speaker` と **完全一致**（入力データの名前。リポジトリ固定リストなし） |
| `anchors[].frame_id` | 任意 | 省略時は bbox 中心が含まれる frame |
| `anchors[].kind` | 任意 | `head` / `stand` / `label`（配置初期は未使用可） |
| `lines[].anchor_id` | 任意 | 明示アンカー（`face_id` と同列） |

**aim 解決の優先（概略）:**  
明示 id → 当該 frame 内 speaker 名マッチ → 複数 aim の幾何 → 単一 aim はコマ内1本目のみ → body 上1/3 → null。  
詳細・モード A/B: GitHub #31 / #35。例: `samples/structure/minimal.json`。

---

## 3. 中間: 配置結果（`layout`）

`place` の出力。`render` の入力。

```json
{
  "schema_version": 1,
  "page": {
    "image_path": "path/to/page.png",
    "width": 1000,
    "height": 1400
  },
  "bubbles": [
    {
      "id": "bub0",
      "line_id": "l1",
      "text": "なんだと！？",
      "tone": "shout",
      "order": 0,
      "bubble_bbox": [420, 80, 720, 280],
      "speaker_face_id": "face0",
      "speaker_face_bbox": [150, 600, 300, 750],
      "frame_id": "f0",
      "score": 12.3,
      "meta": {
        "tone_source": "rule",
        "char_count": 6
      }
    }
  ]
}
```

| フィールド | 必須 | 説明 |
|------------|------|------|
| `text` | **必須** | 後段連携用。焼き文字にしない |
| `tone` | **必須** | normal / shout / whisper / thought / narration / … |
| `bubble_bbox` | **必須** | 枠の外接矩形 |
| `speaker_face_bbox` | 任意 | 尻尾用。narration は null 可 |
| `tone_source` | 任意 | `explicit` / `rule` / `default` |

---

## 4. 出力マニフェスト（`outputs`）

`render` / `run` 終了時に stdout または `out/manifest.json` へ。

```json
{
  "schema_version": 1,
  "status": "ok",
  "page": {
    "image_path": "path/to/page.png",
    "width": 1000,
    "height": 1400
  },
  "files": {
    "art": "path/to/page.png",
    "bubble_layer": "out/page_bubble.png",
    "text_layer": "out/page_text.png",
    "layout_json": "out/page_layout.json",
    "preview": "out/page_preview.png"
  },
  "bubbles": [
    {
      "id": "bub0",
      "line_id": "l1",
      "text": "なんだと！？",
      "tone": "shout",
      "order": 0,
      "bubble_bbox": [420, 80, 720, 280],
      "speaker_face_bbox": [150, 600, 300, 750]
    }
  ],
  "errors": []
}
```

- `preview` は任意（合成確認用）
- 失敗時: `"status": "error"`, `errors: [{ "code", "message", "path?" }]`、exit code ≠ 0

---

## 5. tone 値（v1）

| value | 意味 | 枠のイメージ |
|-------|------|----------------|
| `normal` | 通常 | 楕円 + 尻尾 |
| `shout` | 叫び | ギザギザ + 尻尾 |
| `whisper` | 囁き | 破線楕円 + 尻尾 |
| `thought` | 心の声 | 雲 + 丸連なり |
| `narration` | ナレ・地の文 | 矩形・尻尾なし |

バックログ: `pop`, `flash`, `uni_flash`, `black_uni_flash` 等。

---

## 6. CLI との対応（予定）

| コマンド | 主な入力 | 主な出力 |
|----------|----------|----------|
| `detect` | `image_path` | `detections.json` |
| `place` | `detections.json` + `lines.json`（または統合 input） | `layout.json` |
| `render` | `layout.json` + `out_dir` | layers + `manifest.json` |
| `run` | image + lines + `out_dir` | 上記一括 |

stdout には **マニフェスト JSON のみ**（ログは stderr）を推奨。
