# -*- coding: utf-8 -*-
"""看一眼某一块机关面板长什么样，图上带部件名标注。

调完 tools/blender/build_boards.py 顶部那张参数表以后跑这个，十来秒就能看到结果：

    python tools/preview_board.py spikes 1
    python tools/preview_board.py spring 2
    python tools/preview_board.py push 3
    python tools/preview_board.py all          九块全出一遍

输出：
    renders/parts/board_<类型>_<等级>_parts.png    带部件名标注的图
    renders/parts/board_<类型>_<等级>.png          干净的渲染图

标注的颜色区分固定件和活动件：

    蓝色 = Frame（固定：外框、石缘、铆钉、发光条…）
    红色 = Mover（活动：尖刺 / 弹簧板 / 推板本体）

默认只重新生成模型和图，**不会**刷新 Godot 里的资源。想在游戏里看，加 --game：

    python tools/preview_board.py spikes 1 --game

Blender / Godot 装在别处的话，设环境变量 BLENDER_EXE / GODOT_EXE。
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "renders", "parts")

VARIANTS = ["spring", "spikes", "push"]

BLENDER_CANDIDATES = [
    os.environ.get("BLENDER_EXE", ""),
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "blender",
]
GODOT_CANDIDATES = [
    os.environ.get("GODOT_EXE", ""),
    r"C:\Godot4.7\Godot_v4.7-stable_win64_console.exe",
    r"C:\Godot4.7\Godot_v4.7-stable_win64.exe",
    "godot",
]

FRAME_COLOR = (38, 70, 130)
MOVER_COLOR = (190, 55, 30)


def find(cands, what, env_name):
    for c in cands:
        if not c:
            continue
        if os.path.isfile(c):
            return c
        if os.sep not in c:
            from shutil import which
            p = which(c)
            if p:
                return p
    print("[错误] 找不到 %s。装在别处的话，设环境变量 %s 指向可执行文件。" % (what, env_name))
    sys.exit(1)


def load_font(size, cjk=False):
    """部件名是纯英文，等宽字体最清楚；标题和图例里有中文，必须换带中文字形的字体，
    否则中文会渲染成一串方框。"""
    from PIL import ImageFont
    files = ([r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"] if cjk
             else [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\arial.ttf"])
    for f in files:
        if os.path.isfile(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def annotate(variant, tier):
    """把 Blender 导出的部件坐标画成标注图。

    标签分左右两栏排，再按纵向顺序拉开间距 —— 部件挤在一起时直接把字标在
    原位会全糊成一团，两栏 + 引线是最省事又读得清的画法。
    """
    import json
    from PIL import Image, ImageDraw

    stem = "board_%s_%d" % (variant, tier)
    img_path = os.path.join(OUT_DIR, stem + ".png")
    json_path = os.path.join(OUT_DIR, stem + ".json")
    if not (os.path.isfile(img_path) and os.path.isfile(json_path)):
        print("[跳过] 缺 %s 或 %s" % (img_path, json_path))
        return None

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    shot = Image.open(img_path).convert("RGB")
    sw, sh = shot.size

    margin = 250
    pad_top, pad_bottom = 46, 54
    W, H = sw + margin * 2, sh + pad_top + pad_bottom
    canvas = Image.new("RGB", (W, H), (250, 250, 250))
    canvas.paste(shot, (margin, pad_top))
    d = ImageDraw.Draw(canvas)
    font = load_font(17)
    title_font = load_font(21, cjk=True)
    cjk_font = load_font(16, cjk=True)

    d.text((14, 12), "%s  等级 %d" % (variant, tier), fill=(20, 20, 20), font=title_font)

    items = []
    for name, p in data["parts"].items():
        ix = margin + p["x"] * sw
        iy = pad_top + (1.0 - p["y"]) * sh
        items.append({"name": name, "ix": ix, "iy": iy, "group": p["group"]})

    left = sorted([i for i in items if i["ix"] < margin + sw * 0.5], key=lambda k: k["iy"])
    right = sorted([i for i in items if i["ix"] >= margin + sw * 0.5], key=lambda k: k["iy"])

    def spread(rows):
        """把标签沿纵向拉开，至少隔 gap 像素，不然名字会叠在一起。"""
        gap = 26
        y = pad_top + 6
        for r in rows:
            r["ty"] = max(y, r["iy"])
            y = r["ty"] + gap
        # 超出画布底部就整体往上推
        over = rows[-1]["ty"] - (H - pad_bottom - 10) if rows else 0
        if over > 0:
            for r in rows:
                r["ty"] -= over
        return rows

    for row in spread(left):
        c = FRAME_COLOR if row["group"] == "Frame" else MOVER_COLOR
        tx = margin - 12
        d.line([(tx, row["ty"]), (row["ix"], row["iy"])], fill=c + (0,), width=1)
        d.ellipse([row["ix"] - 3, row["iy"] - 3, row["ix"] + 3, row["iy"] + 3], fill=c)
        w = d.textlength(row["name"], font=font)
        d.text((tx - w, row["ty"] - 9), row["name"], fill=c, font=font)

    for row in spread(right):
        c = FRAME_COLOR if row["group"] == "Frame" else MOVER_COLOR
        tx = margin + sw + 12
        d.line([(tx, row["ty"]), (row["ix"], row["iy"])], fill=c, width=1)
        d.ellipse([row["ix"] - 3, row["iy"] - 3, row["ix"] + 3, row["iy"] + 3], fill=c)
        d.text((tx, row["ty"] - 9), row["name"], fill=c, font=font)

    ly = H - pad_bottom + 12
    d.rectangle([14, ly, 30, ly + 14], fill=FRAME_COLOR)
    d.text((38, ly - 2), "Frame  固定件", fill=(20, 20, 20), font=cjk_font)
    d.rectangle([200, ly, 216, ly + 14], fill=MOVER_COLOR)
    d.text((224, ly - 2), "Mover  活动件", fill=(20, 20, 20), font=cjk_font)

    out = os.path.join(OUT_DIR, stem + "_parts.png")
    canvas.save(out)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_game = "--game" in sys.argv
    variant = args[0] if args else "all"
    tier = int(args[1]) if len(args) > 1 else 0

    if variant != "all" and variant not in VARIANTS:
        print("类型只能是 %s 或 all" % " / ".join(VARIANTS))
        sys.exit(1)

    blender = find(BLENDER_CANDIDATES, "Blender", "BLENDER_EXE")
    os.makedirs(OUT_DIR, exist_ok=True)

    cmd = [blender, "--background", "--python",
           os.path.join("tools", "blender", "build_boards.py"), "--",
           "--out", os.path.join("assets", "models"),
           "--part-map", os.path.join("renders", "parts")]
    if variant != "all":
        cmd += ["--variant", variant]
    if tier:
        cmd += ["--tier", str(tier)]

    r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = r.stdout.decode("utf-8", "replace")
    if r.returncode != 0:
        print(text[-4000:])
        print("[错误] Blender 这一步失败了（退出码 %d）" % r.returncode)
        sys.exit(r.returncode)
    print("生成了 %d 个模型" % text.count("EXPORTED"))

    variants = VARIANTS if variant == "all" else [variant]
    tiers = [tier] if tier else [1, 2, 3]
    made = []
    for v in variants:
        for t in tiers:
            out = annotate(v, t)
            if out:
                made.append(out)
    for m in made:
        print("  " + os.path.relpath(m, ROOT))

    if want_game:
        godot = find(GODOT_CANDIDATES, "Godot", "GODOT_EXE")
        print("\n刷新 Godot 资源（不做这步游戏里还是旧模型）...")
        subprocess.run([godot, "--headless", "--editor", "--quit", "--path", "."],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("好了，进游戏能看到新模型。")


if __name__ == "__main__":
    main()
