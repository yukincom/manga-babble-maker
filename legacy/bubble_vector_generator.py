"""
吹き出しのベクター(SVG)生成モジュール

役割分担:
  bubble_placement_mvp.py  … 「どこに置くか」(bbox候補)を決める
  bubble_vector_generator.py(このファイル) … 「どんな形で置くか」(SVGパス)を作る

トーン(normal/shout/whisper/thought/narration)の判定はこのモジュールの外側 —
既存のComfyUI+QwenVLパイプラインに顔クロップを渡して聞く想定(新規モデル学習は不要)。

出力はSVG。CLIP STUDIO PAINT(PRO/EX)は
[ファイル]→[読み込み]→[ベクター] でSVGをベクターレイヤーとして読み込めるが、
塗りつぶしは輪郭線としてのみ読み込まれる(CSP側の仕様)ので、
読み込み後にCSPのバケツ塗りで白く塗る前提で「線(アウトライン)」を主役にしている。
また読み込み時は72dpi換算でピクセル化されるため、印刷解像度(600dpiなど)の
キャンバスに読み込むと小さく見えることがある点は要注意。
"""
import math
import random


# ---------- 形状(本体アウトライン)のジェネレータ ----------

def _ellipse_pts(cx, cy, rx, ry, seed=0, n=48):
    return [
        (cx + rx * math.cos(2 * math.pi * i / n),
         cy + ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _jagged_pts(cx, cy, rx, ry, seed=0, spikes=14, jitter=0.35):
    rnd = random.Random(seed)
    pts = []
    for i in range(spikes * 2):
        t = math.pi * i / spikes
        base_r = 1.0 if i % 2 == 0 else (1 - jitter)
        r = base_r * (1 + rnd.uniform(-0.08, 0.08))
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return pts


def _cloud_pts(cx, cy, rx, ry, seed=0, bumps=10, n=180):
    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        bump = 1 + 0.12 * math.sin(bumps * t) + rnd.uniform(-0.015, 0.015)
        pts.append((cx + rx * bump * math.cos(t), cy + ry * bump * math.sin(t)))
    return pts


BUBBLE_SHAPES = {
    "normal": _ellipse_pts,
    "shout": _jagged_pts,
    "whisper": _ellipse_pts,
    "thought": _cloud_pts,
}
DASH = {"whisper": "6,5"}  # whisperだけ破線、他は実線


def _pts_to_path_d(pts):
    d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f} "
    d += " ".join(f"L {x:.1f},{y:.1f}" for x, y in pts[1:])
    return d + " Z"


def _nearest_point_on_bbox(px, py, bbox):
    x1, y1, x2, y2 = bbox
    return min(max(px, x1), x2), min(max(py, y1), y2)


def _tail_path_d(cx, cy, rx, ry, target_xy, width=18):
    """吹き出し境界(楕円近似)から話者側の一点へ伸びる三角の尻尾"""
    tx, ty = target_xy
    angle = math.atan2(ty - cy, tx - cx)
    base_x = cx + rx * math.cos(angle)
    base_y = cy + ry * math.sin(angle)
    perp = angle + math.pi / 2
    dx, dy = math.cos(perp) * width / 2, math.sin(perp) * width / 2
    p1 = (base_x + dx, base_y + dy)
    p2 = (base_x - dx, base_y - dy)
    p3 = (tx, ty)
    return _pts_to_path_d([p1, p2, p3])


def generate_bubble_svg_group(
    bubble_bbox,          # (x1,y1,x2,y2) フェーズ1(bubble_placement_mvp)の配置候補
    speaker_face_bbox,     # 話者のface bbox。ナレーションはNone
    bubble_type="normal",  # normal / shout / whisper / thought / narration
    stroke_width=4,
    seed=0,
):
    x1, y1, x2, y2 = bubble_bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = (x2 - x1) / 2, (y2 - y1) / 2
    parts = []

    if bubble_type == "narration":
        d = f"M {x1:.1f},{y1:.1f} L {x2:.1f},{y1:.1f} L {x2:.1f},{y2:.1f} L {x1:.1f},{y2:.1f} Z"
        parts.append(f'<path d="{d}" fill="white" stroke="black" stroke-width="{stroke_width}" />')
        return "\n".join(parts)

    shape_fn = BUBBLE_SHAPES.get(bubble_type, _ellipse_pts)
    body_d = _pts_to_path_d(shape_fn(cx, cy, rx, ry, seed=seed))
    dash = f' stroke-dasharray="{DASH[bubble_type]}"' if bubble_type in DASH else ""
    parts.append(
        f'<path d="{body_d}" fill="white" stroke="black" '
        f'stroke-width="{stroke_width}"{dash} />'
    )

    if speaker_face_bbox is not None:
        fx1, fy1, fx2, fy2 = speaker_face_bbox
        # 顎のあたりを狙う(顔bboxの下端寄り)
        aim_bbox = (fx1, fy1, fx2, fy2 + (fy2 - fy1) * 0.3)
        target = _nearest_point_on_bbox(cx, cy, aim_bbox)
        if bubble_type == "thought":
            # 心の声は尻尾の代わりに小さい丸を話者へ向けて並べる
            for i, frac in enumerate((0.32, 0.56, 0.78)):
                bx = cx + (target[0] - cx) * frac
                by = cy + (target[1] - cy) * frac
                r = 11 - i * 3
                parts.append(
                    f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{r}" '
                    f'fill="white" stroke="black" stroke-width="{stroke_width * 0.6:.1f}" />'
                )
        else:
            tail_d = _tail_path_d(cx, cy, rx, ry, target)
            parts.append(
                f'<path d="{tail_d}" fill="white" stroke="black" '
                f'stroke-width="{stroke_width}" stroke-linejoin="round" />'
            )

    return "\n".join(parts)
