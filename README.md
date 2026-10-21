# manga-babble-maker

**開発終了（2026-10-21）**。ニャムル側の漫画制作パイプラインへ一本化するため、この独立ツールの開発を中止しました。コード・開発履歴・ローカルで作成した素材と試験出力を公開記録として残します。[終了と保存範囲](docs/retirement-2026-10-21.md)を参照してください。以下の手順は開発当時のものです。

完成したマンガ絵とセリフ JSON から、吹き出しの**配置・種類・レイヤ出力**を行うツール。  
**ネーム先（モードB）**: 画像なしでも `frames` + `anchors`（話者の頭 bbox）+ セリフで配置できる。

- **配置**: aim（検出 face ∪ ネーム anchor）を避けた空き領域
- **種類 (tone)**: セリフ規則（VLM 非依存）
- **出力**: `bubble` PNG / `text` PNG / `layout.json`（文字データ必須）
- **検出**: [RT-DETRv4-X Manga109-s v2](https://huggingface.co/tori29umai/rtdetrv4-x-manga109s_v2) ONNX（ローカル）— モードA
- **操作**: CLI → 同じ core を MCP で薄いラップ（エージェント向け）

方針の正: [`Agent.md`](./Agent.md) · 配置ルール: [#31](https://github.com/yukincom/manga-babble-maker/issues/31) · モードB: [#35](https://github.com/yukincom/manga-babble-maker/issues/35)

## セットアップ

```bash
cd manga-babble-maker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# モデル（約 240MB・git 対象外）
# 手順は models/README.md
curl -L -o models/rtdetrv4-x-manga109s_v2/model.onnx \
  "https://huggingface.co/tori29umai/rtdetrv4-x-manga109s_v2/resolve/main/model.onnx"
```

## CLI

リポジトリルートで（`PYTHONPATH=.` または editable install）:

```bash
export PYTHONPATH=.

# サンプル detections で place + render（ONNX 不要）
python -m manga_babble run \
  --image /dev/null \
  --lines samples/demo_lines.json \
  --detections samples/demo_detections.json \
  --out-dir outputs/demo \
  --no-preview
# ※ image は layout 用。固定 detections 利用時はダミーでも可だが、
#   プレビュー合成するなら実画像パスを渡す。

# 推奨: 固定 detections で place → render
python -m manga_babble place \
  --detections samples/demo_detections.json \
  --lines samples/demo_lines.json \
  --out outputs/demo/layout.json

python -m manga_babble render \
  --layout outputs/demo/layout.json \
  --out-dir outputs/demo

# 実画像 + ONNX 一括
python -m manga_babble run \
  --image path/to/page.png \
  --lines samples/demo_lines.json \
  --out-dir outputs/page \
  --model models/rtdetrv4-x-manga109s_v2/model.onnx

# モードB: 構造のみ（画像不要）。frames + anchors + lines
python -m manga_babble place \
  --detections samples/structure/minimal.json \
  --lines samples/structure/minimal.json \
  --out outputs/structure/layout.json
```

`anchors[].speaker` と `lines[].speaker` を同じ文字列にすると、尻尾・近傍がその頭 bbox に向く（検出 face 不要）。

成功時、**stdout にマニフェスト JSON**（ログは stderr）。

| 出力 | 内容 |
|------|------|
| `*_bubble.png` | 枠・尻尾のみ |
| `*_text.png` | 文字のみ |
| `*_layout.json` | text / tone / bbox（後段連携の正） |
| `*_preview.png` | 任意の合成確認 |
| `*_manifest.json` | パス一覧 + bubbles |

## MCP（エージェント）

```bash
pip install mcp
python -m manga_babble.mcp_server
```

設定例: [`docs/mcp-config.example.json`](./docs/mcp-config.example.json)

Tools: `detect_page` / `place_bubbles` / `render_layers` / `run_pipeline_tool`

本ツールは原稿を勝手にアップロードしません。クラウド LLM に何を載せるかはエージェント設定次第です。

## テスト

```bash
pip install pytest
PYTHONPATH=. pytest -q
```

## レイアウト

```text
manga_babble/     # core + CLI + MCP
samples/          # 固定 detections / lines
docs/             # 計画・スキーマ
models/           # ONNX（重みは gitignore）
legacy/           # 旧 MVP（参考）
```
