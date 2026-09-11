"""
把地图截图转成我们的关卡 JSON。

用法：
  python tools/map_from_image.py --image DungeonWarfareMap01.png \
      --out data/levels/dw_01.json --name "地牢战争 01" \
      --core 2,3 --core-size 2x2 --entrance 10,14-12,14

做法：
  1) 对图里的颜色做 k-means，按"最蓝 / 最亮的暖色 / 中间暖色 / 最暗"自动分成
     空地、墙、地面、图外四类；
  2) 从蓝色块的边界游程自动推出格子间距和原点（不用手填）；
  3) 每格取中心区域投票定类型，砖缝的暗色和图标的白色不参与投票。

输出的 grid 直接就是我们的格子类型：0 空地 1 地面 2 墙 3 障碍 4 桥 5 核心。
认错的地方直接改 JSON 就行。
"""

import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw


def kmeans(sample, k, iters=30, seed=0):
    rng = np.random.default_rng(seed)
    cent = sample[rng.choice(len(sample), k, replace=False)].astype(float)
    lab = np.zeros(len(sample), int)
    for _ in range(iters):
        d = ((sample[:, None, :] - cent[None, :, :]) ** 2).sum(2)
        lab = d.argmin(1)
        for i in range(k):
            if (lab == i).any():
                cent[i] = sample[lab == i].mean(0)
    return cent, lab


def classify_colors(a, k=6, seed=0):
    """返回每像素的语义类别：0 图外/阴影 1 地面 2 空地 3 墙"""
    h, w, _ = a.shape
    m = max(h, w)
    inset = max(int(min(h, w) * 0.05), 10)
    sub = a[inset:h - inset, inset:w - inset].reshape(-1, 3)
    rng = np.random.default_rng(seed)
    n = min(60000, len(sub))
    cent, _ = kmeans(sub[rng.choice(len(sub), n, replace=False)], k, seed=seed)

    lum = cent.mean(1)
    blueness = cent[:, 2] - (cent[:, 0] + cent[:, 1]) / 2.0
    warmth = cent[:, 0] - cent[:, 2]

    sem = np.zeros(k, int)
    void_i = int(np.argmax(blueness))
    sem[void_i] = 2
    warm = [i for i in range(k) if i != void_i and warmth[i] > 15]
    warm.sort(key=lambda i: -lum[i])
    # 砖缝、投影和图外的暗棕色也是暖色，但亮度明显低一档，不能算进地面
    if warm:
        floor_floor = lum[warm[0]] * 0.55
        warm = [i for i in warm if lum[i] >= floor_floor]
    # 最亮的两档暖色当墙（墙有亮顶和砖体两层），其余暖色当地面
    for i in warm[:2]:
        sem[i] = 3
    for i in warm[2:]:
        sem[i] = 1
    for i in range(k):
        if i != void_i and i not in warm:
            sem[i] = 0          # 暗色（砖缝/阴影/图外）和白色图标都不参与投票
    d = ((a[:, :, None, :] - cent[None, None, :, :]) ** 2).sum(3)
    return sem[d.argmin(2)], cent, sem


def detect_pitch(mask, lo=8, hi=60):
    """一块 n 格宽的区域，它的像素游程长度是 n*间距 - 固定内缩量。
    所以把常见的游程长度排序后，相邻两档之间的差就是间距。"""
    lens = Counter()
    for line in list(mask) + list(mask.T):
        n = 0
        for v in line:
            if v:
                n += 1
            elif n:
                lens[n] += 1
                n = 0
        if n:
            lens[n] += 1
    if not lens:
        return lo
    thresh = max(lens.values()) * 0.12
    common = sorted(l for l, c in lens.items() if c >= thresh and l >= lo * 0.6)
    # 把相差 <=2px 的长度并成一档
    groups = []
    for l in common:
        if groups and l - groups[-1][-1] <= 2:
            groups[-1].append(l)
        else:
            groups.append([l])
    centers = [sum(g) / len(g) for g in groups]
    diffs = Counter()
    for i in range(1, len(centers)):
        d = centers[i] - centers[i - 1]
        if lo <= d <= hi:
            diffs[int(round(d))] += 1
    if not diffs:
        return int(round(centers[0])) if centers else lo
    top = max(diffs.values())
    return min(d for d, c in diffs.items() if c == top)


def detect_origin(mask, pitch, axis):
    """蓝块在格子里居中内缩，取起止边界的众数反推格子原点"""
    starts, ends = Counter(), Counter()
    arr = mask if axis == 0 else mask.T
    for line in arr:
        prev = False
        for i, v in enumerate(line):
            if v and not prev:
                starts[i % pitch] += 1
            if prev and not v:
                ends[i % pitch] += 1
            prev = v
    if not starts or not ends:
        return 0
    s = max(starts, key=starts.get)
    e = max(ends, key=ends.get)
    inset = ((s - e) % pitch) / 2.0     # 两侧内缩量
    return int(round((s - inset) % pitch))


def parse_cell(text):
    x, y = text.split(",")
    return int(x), int(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--pitch", type=int, default=0, help="格子像素间距，0=自动")
    ap.add_argument("--origin", default="", help="x,y 格子原点像素，留空=自动")
    ap.add_argument("--size", default="", help="列x行，留空=自动")
    ap.add_argument("--core", default="", help="核心左上角 x,y")
    ap.add_argument("--core-size", default="2x2")
    ap.add_argument("--entrance", default="", help="入口格 x,y 或 x,y-x,y（会被改成地面）")
    ap.add_argument("--wall", default="", help="强制设成墙的区域，x,y-x,y，可用分号分隔多个")
    ap.add_argument("--void", default="", help="强制设成空地的区域，同上")
    ap.add_argument("--pad", type=float, default=0.2, help="每格只取中心多大比例之外的边不采样，越大越不受邻格污染")
    ap.add_argument("--preview", default="", help="输出一张对照图")
    args = ap.parse_args()

    im = Image.open(args.image).convert("RGB")
    a = np.asarray(im).astype(float)
    sem, cent, semmap = classify_colors(a)
    print("颜色聚类 -> 语义（0图外 1地面 2空地 3墙）:")
    for i in range(len(cent)):
        print("   (%3d,%3d,%3d) -> %d" % (cent[i][0], cent[i][1], cent[i][2], semmap[i]))

    void_mask = sem == 2
    pitch = args.pitch or detect_pitch(void_mask)
    if args.origin:
        ox, oy = parse_cell(args.origin)
    else:
        ox = detect_origin(void_mask, pitch, 0)
        oy = detect_origin(void_mask, pitch, 1)
    print("格子间距 %d px，原点 (%d,%d)" % (pitch, ox, oy))

    h, w = sem.shape
    if args.size:
        nx, ny = (int(v) for v in args.size.lower().split("x"))
    else:
        solid = (sem == 3) | (sem == 2) | (sem == 1)
        ys, xs = np.where(solid)
        nx = int(np.ceil((xs.max() + 1 - ox) / pitch))
        ny = int(np.ceil((ys.max() + 1 - oy) / pitch))
    print("网格 %d x %d" % (nx, ny))

    pad = max(int(pitch * args.pad), 2)
    grid = []
    for gy in range(ny):
        row = []
        for gx in range(nx):
            px, py = ox + gx * pitch, oy + gy * pitch
            blk = sem[max(py + pad, 0):min(py + pitch - pad, h),
                      max(px + pad, 0):min(px + pitch - pad, w)]
            if blk.size == 0:
                row.append(0)
                continue
            c = np.bincount(blk.ravel(), minlength=4)
            wall_v, void_v, floor_v = c[3], c[2], c[1]
            if max(wall_v, void_v, floor_v) == 0:
                row.append(0)
            elif void_v >= wall_v and void_v >= floor_v:
                row.append(0)
            elif wall_v >= floor_v:
                row.append(2)
            else:
                row.append(1)
        grid.append(row)

    def put_rect(spec, value):
        for part in spec.split(";"):
            if not part.strip():
                continue
            if "-" in part:
                (x0, y0), (x1, y1) = (parse_cell(p) for p in part.split("-"))
            else:
                x0, y0 = parse_cell(part)
                x1, y1 = x0, y0
            for y in range(min(y0, y1), max(y0, y1) + 1):
                for x in range(min(x0, x1), max(x0, x1) + 1):
                    if 0 <= y < ny and 0 <= x < nx:
                        grid[y][x] = value

    if args.wall:
        put_rect(args.wall, 2)
    if args.void:
        put_rect(args.void, 0)
    if args.entrance:
        put_rect(args.entrance, 1)
    if args.core:
        cx, cy = parse_cell(args.core)
        cw, ch = (int(v) for v in args.core_size.lower().split("x"))
        put_rect("%d,%d-%d,%d" % (cx, cy, cx + cw - 1, cy + ch - 1), 5)

    # --- 连通性检查：从核心 BFS，看入口和各地面块能不能到
    core_cells = [(x, y) for y in range(ny) for x in range(nx) if grid[y][x] == 5]
    walkable = lambda x, y: 0 <= x < nx and 0 <= y < ny and grid[y][x] in (1, 4, 5)
    seen = set(core_cells)
    stack = list(core_cells)
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if walkable(x + dx, y + dy) and (x + dx, y + dy) not in seen:
                seen.add((x + dx, y + dy))
                stack.append((x + dx, y + dy))
    total = sum(1 for y in range(ny) for x in range(nx) if walkable(x, y))
    border_open = [(x, y) for y in range(ny) for x in range(nx)
                   if walkable(x, y) and (x == 0 or y == 0 or x == nx - 1 or y == ny - 1)]
    orphan = [(x, y) for y in range(ny) for x in range(nx) if walkable(x, y) and (x, y) not in seen]
    print("可行走格 %d，从核心可达 %d（不可达 %d）" % (total, len(seen), len(orphan)))
    if orphan:
        print("  走不到核心的格子: %s" % (orphan[:40],))
    print("地图边缘的开口: %s" % (border_open if border_open else "无 —— 引擎会报「找不到入口」"))
    for c in border_open:
        if c not in seen:
            print("  警告：边缘开口 %s 走不到核心" % (c,))

    level = {
        "name": args.name or os.path.basename(args.image),
        "_comment": "由 tools/map_from_image.py 从 %s 转换而来。格子类型：0 空地 1 地面 2 墙 3 障碍 4 桥 5 核心。" % os.path.basename(args.image),
        "grid": ["".join(str(v) for v in row) for row in grid],
        "entrance": [p.strip() for p in args.entrance.split(";") if p.strip()] if args.entrance else [],
        "allowed_traps": ["spikes", "tar", "launcher", "push_wall", "saw"],
        "waves": [
            {"name": "第1波 · 小兵试水", "groups": [{"enemy": "grunt", "count": 10, "interval": 0.5, "delay": 0.0}]},
            {"name": "第2波 · 小兵成堆", "groups": [{"enemy": "grunt", "count": 14, "interval": 0.3, "delay": 0.0},
                                                 {"enemy": "grunt", "count": 10, "interval": 0.3, "delay": 6.0}]},
            {"name": "第3波 · 中型加入", "groups": [{"enemy": "grunt", "count": 14, "interval": 0.35, "delay": 0.0},
                                                 {"enemy": "berserker", "count": 4, "interval": 1.2, "delay": 3.0}]},
            {"name": "第4波 · 冷却压力", "groups": [{"enemy": "grunt", "count": 18, "interval": 0.25, "delay": 0.0},
                                                 {"enemy": "berserker", "count": 6, "interval": 0.9, "delay": 4.0}]},
            {"name": "第5波 · 重型登场", "groups": [{"enemy": "grunt", "count": 14, "interval": 0.3, "delay": 0.0},
                                                 {"enemy": "berserker", "count": 5, "interval": 1.0, "delay": 3.0},
                                                 {"enemy": "troll", "count": 2, "interval": 4.0, "delay": 7.0}]},
        ],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(level, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % args.out)

    if args.preview:
        COL = {0: (40, 45, 200), 1: (205, 180, 135), 2: (150, 92, 45), 3: (110, 100, 95),
               4: (200, 170, 120), 5: (60, 200, 200)}
        rec = Image.new("RGB", (nx * pitch, ny * pitch), (0, 0, 0))
        dr = ImageDraw.Draw(rec)
        for gy in range(ny):
            for gx in range(nx):
                dr.rectangle([gx * pitch, gy * pitch, gx * pitch + pitch - 1, gy * pitch + pitch - 1],
                             fill=COL.get(grid[gy][gx], (255, 0, 255)), outline=(70, 70, 70))
        out = Image.new("RGB", (max(im.width, rec.width + ox), im.height + rec.height + 8), (0, 0, 0))
        out.paste(im, (0, 0))
        out.paste(rec, (ox, im.height + 8))
        out.save(args.preview)
        print("对照图 %s" % args.preview)


if __name__ == "__main__":
    sys.exit(main())
