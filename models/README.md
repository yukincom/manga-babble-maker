# Models

## RT-DETRv4-X Manga109-s v2

**必要:** はい。推論には Hugging Face 上の **`model.onnx`（約 250MB）をローカルに置く**必要があります。  
リポジトリには含めません（`.gitignore` 対象・サイズ大）。

- カード: https://huggingface.co/tori29umai/rtdetrv4-x-manga109s_v2
- ファイル: `model.onnx`（opset 17, 入力 `1×3×1280×1280`）
- ライセンス: Apache 2.0（学習データ Manga109-s の規約にも注意）

### ダウンロード

仮想環境を有効化したうえで、リポジトリルートから:

```bash
# 方法 A: huggingface-cli（推奨）
pip install huggingface_hub
huggingface-cli download tori29umai/rtdetrv4-x-manga109s_v2 model.onnx \
  --local-dir models/rtdetrv4-x-manga109s_v2 \
  --local-dir-use-symlinks False

# 方法 B: curl
mkdir -p models/rtdetrv4-x-manga109s_v2
curl -L -o models/rtdetrv4-x-manga109s_v2/model.onnx \
  "https://huggingface.co/tori29umai/rtdetrv4-x-manga109s_v2/resolve/main/model.onnx"
```

配置後のパス:

```text
models/rtdetrv4-x-manga109s_v2/model.onnx
```

### 注意

- ダウンロードは **モデル重みの取得**であり、原稿の外部送信ではありません。
- 推論自体は `onnxruntime` で **完全ローカル**です。
- オフライン作業するなら、一度取得した `model.onnx` をこのディレクトリに置いておけばネット不要です。
