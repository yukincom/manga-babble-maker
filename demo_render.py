"""見た目確認用デモ: 配置候補(bubble_placement_mvp) + ベクター生成(bubble_vector_generator) を
1枚のSVGにまとめて出力する。body/faceは実際には検出結果のbboxを渡す想定だが、
ここでは動作確認のため簡易的な矩形で描いている。
"""
from bubble_placement_mvp import compute_bubble_candidates
from bubble_vector_generator import generate_bubble_svg_group

FRAME = (0, 0, 1000, 1400)
BODIES = [(100, 600, 400, 1400), (600, 700, 950, 1400)]
FACES = [(150, 600, 300, 750), (680, 700, 820, 830)]

candidates = compute_bubble_candidates(FRAME, BODIES, FACES, top_k=3)

svg_parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{FRAME[0]} {FRAME[1]} '
    f'{FRAME[2]} {FRAME[3]}">',
    f'<rect x="{FRAME[0]}" y="{FRAME[1]}" width="{FRAME[2]}" height="{FRAME[3]}" '
    f'fill="none" stroke="black" stroke-width="6" />',
]

# body/faceを検出結果の可視化として薄く描画(実運用では非表示にしてOK)
for bx in BODIES:
    svg_parts.append(
        f'<rect x="{bx[0]}" y="{bx[1]}" width="{bx[2]-bx[0]}" height="{bx[3]-bx[1]}" '
        f'fill="none" stroke="blue" stroke-width="2" stroke-dasharray="4,4" />'
    )
for fx in FACES:
    svg_parts.append(
        f'<rect x="{fx[0]}" y="{fx[1]}" width="{fx[2]-fx[0]}" height="{fx[3]-fx[1]}" '
        f'fill="none" stroke="hotpink" stroke-width="2" stroke-dasharray="4,4" />'
    )

# 候補1: キャラ1への通常吹き出し / 候補2: キャラ2への叫び / 候補3: 心の声
bubble_types = ["normal", "shout", "thought"]
speakers = [FACES[0], FACES[1], FACES[0]]

for i, cand in enumerate(candidates):
    btype = bubble_types[i % len(bubble_types)]
    speaker = speakers[i % len(speakers)]
    group = generate_bubble_svg_group(
        cand["bbox"], speaker, bubble_type=btype, seed=i,
    )
    svg_parts.append(f"<!-- candidate {i+1}: {btype} -->")
    svg_parts.append(group)

svg_parts.append("</svg>")
svg = "\n".join(svg_parts)

with open("/home/claude/preview.svg", "w") as f:
    f.write(svg)

print("wrote /home/claude/preview.svg")
