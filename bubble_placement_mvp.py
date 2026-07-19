"""
吹き出し(text)配置候補を提案するMVPヒューリスティック

前提:
  rtdetrv4-x-manga109s_v2 で1コマ分の body / face の bbox が取れている状態から、
  そのコマ内で「体・顔と重ならない、かつ十分な広さがある」領域を吹き出し配置候補として
  ランキング付きで返す。学習は不要 — 幾何計算のみ。

参考にした知見(既存研究の踏襲ポイント):
  - 吹き出しはキャラクターの顔を隠さないことが読みやすさの絶対条件
    (MangaFlowのBubble Placement Scoreも「顔を隠していないか」を主指標にしている)
  - script/speaker-face mappingで話者近傍に吹き出しを置き、
    レイアウトアルゴリズムで顔・パネル境界との重なりを避ける、という設計は
    Automatic Comic Generation (Yao et al., 2021 / Preu et al. / Hong et al.) でも採用されている
"""
import numpy as np
import cv2


def compute_bubble_candidates(
    frame_bbox,       # (x1, y1, x2, y2) パネル全体の座標
    body_bboxes,       # [(x1,y1,x2,y2), ...] コマ内のbody bbox
    face_bboxes,       # [(x1,y1,x2,y2), ...] コマ内のface bbox
    resolution=200,     # マスク解像度(速度と精度のトレードオフ、200で十分実用的)
    margin_ratio=0.03,  # 顔・体の周囲に持たせる余白(吹き出しの尻尾がめり込まないように)
    top_k=3,
):
    fx1, fy1, fx2, fy2 = frame_bbox
    fw, fh = fx2 - fx1, fy2 - fy1
    if fw <= 0 or fh <= 0:
        return []

    # マスクは正方形にせず、パネルの縦横比に合わせる。
    # 正方形マスクに押し込むとx/yで1ピクセルあたりの実距離が変わってしまい、
    # distanceTransformが返す「半径」が実寸で円にならず歪む。
    res_x = resolution
    res_y = max(1, round(resolution * fh / fw))

    occupied = np.zeros((res_y, res_x), dtype=np.uint8)
    # パネルの枠自体も「壁」として扱う(枠ギリギリに吹き出しがはみ出さないように)
    border = max(1, int(res_x * margin_ratio))
    occupied[:border, :] = 1
    occupied[-border:, :] = 1
    occupied[:, :border] = 1
    occupied[:, -border:] = 1

    def to_mask_coords(bbox):
        x1, y1, x2, y2 = bbox
        mx1 = int((x1 - fx1) / fw * res_x)
        my1 = int((y1 - fy1) / fh * res_y)
        mx2 = int((x2 - fx1) / fw * res_x)
        my2 = int((y2 - fy1) / fh * res_y)
        return (
            max(mx1, 0), max(my1, 0),
            min(mx2, res_x), min(my2, res_y),
        )

    margin = max(1, int(res_x * margin_ratio))
    for bbox in list(body_bboxes) + list(face_bboxes):
        mx1, my1, mx2, my2 = to_mask_coords(bbox)
        occupied[
            max(0, my1 - margin):min(res_y, my2 + margin),
            max(0, mx1 - margin):min(res_x, mx2 + margin),
        ] = 1

    px_per_unit = fw / res_x  # res_x/res_yは同じ実距離スケールになるよう揃えてある
    HALF_W_RATIO, HALF_H_RATIO = 0.95, 0.8  # 吹き出しは横長寄りにする

    results = []
    for _ in range(top_k):
        # 距離変換: 各「空き」ピクセルが、最も近い「占有」ピクセルからどれだけ離れているか
        # occupiedは後述の通りループのたびに「これまで選んだ候補」も足し込んで更新するので、
        # 既に置いた吹き出しと重なる場所は次の候補として選ばれなくなる
        free = (1 - occupied).astype(np.uint8)
        dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)
        idx = np.unravel_index(np.argmax(dist), dist.shape)
        peak_val = dist[idx]
        if peak_val <= 1:  # 十分な広さがなければ打ち切り
            break
        cy, cx = idx

        half_w_mask = peak_val * HALF_W_RATIO
        half_h_mask = peak_val * HALF_H_RATIO
        mx1, my1 = cx - half_w_mask, cy - half_h_mask
        mx2, my2 = cx + half_w_mask, cy + half_h_mask

        # 選んだ候補自身の矩形を「占有」に足し込む → 次のループでここには置かれなくなる
        occupied[
            max(0, int(my1)):min(res_y, int(my2) + 1),
            max(0, int(mx1)):min(res_x, int(mx2) + 1),
        ] = 1

        cx_real, cy_real = fx1 + cx * px_per_unit, fy1 + cy * px_per_unit
        half_w, half_h = half_w_mask * px_per_unit, half_h_mask * px_per_unit
        bbox = (cx_real - half_w, cy_real - half_h, cx_real + half_w, cy_real + half_h)
        # 安全のためパネル範囲内にクリップ(境界を壁扱いしているので通常は不要だが念のため)
        bbox = (
            max(fx1, bbox[0]), max(fy1, bbox[1]),
            min(fx2, bbox[2]), min(fy2, bbox[3]),
        )
        results.append({"bbox": bbox, "score": float(peak_val)})
    return results


if __name__ == "__main__":
    # ダミーデータでの動作確認(実際は検出モデルの出力bboxをそのまま渡す)
    frame = (0, 0, 1000, 1400)
    bodies = [(100, 600, 400, 1400), (600, 700, 950, 1400)]
    faces = [(150, 600, 300, 750), (680, 700, 820, 830)]

    candidates = compute_bubble_candidates(frame, bodies, faces)
    for i, c in enumerate(candidates):
        bbox = tuple(round(v) for v in c["bbox"])
        print(f"候補{i + 1}: bbox={bbox}  score={c['score']:.1f}")
