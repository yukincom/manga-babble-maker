# Shape templates

楕円（`normal`）以外はテンプレート PNG から選択する。

## レイアウト

```text
assets/shapes/
  fun-cloud/     # 楽しい・明るい発話（心の声ではない）
    fun-cloud_01.png … fun-cloud_06.png
  jagged/        # 叫び・ギザ
    jagged_01.png … jagged_05.png
```

## 意味

| トークン | 用途 | ディレクトリ |
|----------|------|----------------|
| `fun-cloud` | 楽しい・明るい**声** | `fun-cloud/` |
| `giza` / jagged | 叫び | `jagged/` |
| `thought` | 心の声 | テンプレなし（楕円＋丸） |
| `normal` | 普通 | 手続き楕円 |

## 選択

1. `meta.template_id`（例 `fun-cloud_03`）
2. なければ `seed % 枚数`

## ファイル

- PNG、背景透明推奨
- 白塗り＋黒線
- 短辺大きめ推奨
