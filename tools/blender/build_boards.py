"""
机关面板：三种面板 × 三个等级，照 ref/3 boards.png 做。

  spring  弹簧板   地面，方形，铰链边一排弹簧，板面一个朝前的箭头
  spikes  尖刺板   地面，方形，四根尖刺从凹槽里升起
  push    推板     墙面，**宽高比 2:1**，中间一块带宝石的板往前推

每种三个等级，主要区别是颜色（1 青 / 2 紫 / 3 橙金），同时花纹逐级变复杂：
等级越高，边框越厚、叶片越多、内板从方形变成花瓣形。

**活动部分和固定部分是分开的**（用户要求）：

  Frame   固定：石缘、金色边框、角铆钉、弹簧/发光条
  Mover   活动：尖刺 / 弹簧板 / 推板本体

Godot 里 TrapView 只认 anim.part 这个名字，所以三种面板的活动件统一叫 `Mover`，
接进游戏时不用给每种单独配。

约定和 build_traps.py 一致：
- 按 **1×1 格**建（x/y 在 ±0.5 内），Godot 里按 cell_size 缩放；
- 朝 **+Y**，glTF 转 Y-up 后就是 Godot 的前方 -Z；
- 墙面板的原点在墙面上，本体往 +Y 伸出；
- 材质 `board_accent` 是等级色（自发光），Godot 里也能再换。

用法：
  blender --background --python tools/blender/build_boards.py -- \
      --variant spikes --tier 2 --out assets/models/board_spikes_2.glb
  不传 --variant / --tier 就把 9 个全导出（--out 当目录用）。
  --render-dir renders/boards 顺便出预览图。

注：本文件的基础图元和 build_traps.py 有重叠。仓库里每个建模脚本都是自包含的
（build_swordman.py 也一样），改一个不会弄坏另一个 —— 这三种面板将来多半会
取代 build_traps.py 里对应的三种，到时候再合并。
"""

import bpy
import math
import os
import sys


def to_linear(c):
    """sRGB -> 线性。Blender 的 Base Color 收的是**线性**值，
    直接把从参考图上取的 sRGB 数值填进去，渲染出来会明显发灰发白。"""
    def f(u):
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4
    return (f(c[0]), f(c[1]), f(c[2]), 1.0)


# 等级色：青 / 紫 / 橙金。参考图里三个等级主要就是这个色的区别。
ACCENT = {
    1: (0.16, 0.78, 0.94),
    2: (0.58, 0.31, 0.95),
    3: (1.00, 0.63, 0.12),
}

# 以下都按 sRGB 写（就是在参考图上吸到的值），用的时候转线性
COLORS = {
    "board_stone":     (0.94, 0.93, 0.90),   # 奶白石材，和场景地面一个调子
    "board_stone_mid": (0.66, 0.68, 0.72),   # 内板的灰
    "board_gold":      (0.85, 0.67, 0.26),
    "board_gold_dark": (0.52, 0.37, 0.12),
    "board_socket":    (0.16, 0.18, 0.24),   # 凹槽的暗色
    "board_accent":    (1.0, 1.0, 1.0),      # 运行时按等级替换
}

EMISSIVE = ("board_accent",)

VARIANTS = ["spring", "spikes", "push"]
TIERS = [1, 2, 3]

_tier = 1


# ----------------------------------------------------------------- 工具

def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mat(name):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    c = ACCENT[_tier] if name == "board_accent" else COLORS[name]
    b.inputs["Base Color"].default_value = to_linear(c)
    # 等级色不能太光滑：朝上的平面（箭头、叶片）会被高光烧白，紫色最明显
    b.inputs["Roughness"].default_value = 0.30 if name == "board_gold" else (
        0.48 if name == "board_accent" else 0.78)
    if "Metallic" in b.inputs:
        b.inputs["Metallic"].default_value = 0.85 if name.startswith("board_gold") else 0.0
    # 宝石和发光条微微发光。强度别给大，Standard 视图变换不做色调映射，
    # 给到 1.0 以上直接烧成白的，等级色就看不出来了。
    if name in EMISSIVE and "Emission Color" in b.inputs:
        b.inputs["Emission Color"].default_value = to_linear(c)
        if "Emission Strength" in b.inputs:
            b.inputs["Emission Strength"].default_value = 0.30
    return m


def joint(name, pos=(0, 0, 0), parent=None, rotation=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.08
    e.location = pos
    if rotation:
        e.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(e)
    if parent:
        e.parent = parent
    return e


def add(name, verts, faces, material, parent, bevel=0.008):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.materials.append(mat(material))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if bevel > 0:
        b = ob.modifiers.new("Bevel", "BEVEL")
        b.width = bevel
        b.segments = 2
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(35)
    ob.parent = parent
    return ob


def box(name, center, size, material, parent, bevel=0.008, rotation=None):
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    v = [(cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
         (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
         (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
         (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz)]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    ob = add(name, v, f, material, parent, bevel)
    if rotation:
        ob.rotation_euler = rotation
    return ob


def cyl(name, center, radius, height, material, parent, axis="z", sides=16, bevel=0.005,
        rot_z=0.0):
    cx, cy, cz = center
    v, f = [], []
    h = height / 2.0
    for sign in (-1, 1):
        for i in range(sides):
            a = 2 * math.pi * i / sides + rot_z
            p = [math.cos(a) * radius, math.sin(a) * radius, sign * h]
            if axis == "x":
                p = [sign * h, p[0], p[1]]
            elif axis == "y":
                p = [p[0], sign * h, p[1]]
            v.append((cx + p[0], cy + p[1], cz + p[2]))
    for i in range(sides):
        j = (i + 1) % sides
        f.append((i, j, j + sides, i + sides))
    f.append(tuple(range(sides - 1, -1, -1)))
    f.append(tuple(range(sides, sides * 2)))
    return add(name, v, f, material, parent, bevel)


def _unmap(u, v, w, axis):
    """轮廓平面 -> 世界。axis='z' 时轮廓在 XY、沿 Z 挤（地面板）；
    axis='y' 时轮廓在 XZ、沿 Y 挤（墙面板）。"""
    return (u, w, v) if axis == "y" else (u, v, w)


def prism(name, pts, a0, a1, material, parent, bevel=0.006, axis="z"):
    """把一条 2D 轮廓（逆时针）挤出成柱体。箭头、叶片、花瓣内板都靠它。"""
    # axis='y' 的映射是个镜像（行列式为负），不把点序反过来法线会朝里
    p = list(reversed(pts)) if axis == "y" else list(pts)
    n = len(p)
    v = [_unmap(q[0], q[1], a0, axis) for q in p] + [_unmap(q[0], q[1], a1, axis) for q in p]
    f = []
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, j + n, i + n))
    f.append(tuple(range(n - 1, -1, -1)))
    f.append(tuple(range(n, 2 * n)))
    return add(name, v, f, material, parent, bevel)


def pyramid(name, center, base, height, material, parent, bevel=0.004):
    cx, cy, cz = center
    h = base / 2.0
    v = [(cx - h, cy - h, cz), (cx + h, cy - h, cz), (cx + h, cy + h, cz), (cx - h, cy + h, cz),
         (cx, cy, cz + height)]
    f = [(0, 1, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)]
    return add(name, v, f, material, parent, bevel)


def gem(name, center, radius, inner, height, material, parent, points=4, rot=0.0, axis="z"):
    """四角宝石：星形轮廓，前后各收一个尖，做出刻面。参考图里每块板中间都有一颗。
    axis='y' 用于墙面板 —— 尖朝 +Y 顶出来，不然从正面看是一条缝。"""
    cu, cv, cw = (center[0], center[2], center[1]) if axis == "y" else center
    n = points * 2
    pts = []
    for i in range(n):
        a = rot + math.pi * i / points
        r = radius if i % 2 == 0 else inner
        pts.append((cu + math.cos(a) * r, cv + math.sin(a) * r))
    if axis == "y":
        pts = list(reversed(pts))
    v = [_unmap(p[0], p[1], cw, axis) for p in pts]
    top = len(v)
    v.append(_unmap(cu, cv, cw + height, axis))
    bot = len(v)
    v.append(_unmap(cu, cv, cw - height * 0.5, axis))
    f = []
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, top))
        f.append((j, i, bot))
    return add(name, v, f, material, parent, bevel=0.003)


def leaf_pts(length, width, steps=7):
    """叶片轮廓：两头尖的杏仁形。参考图里到处点缀着这个。"""
    pts = []
    for i in range(steps + 1):
        t = i / float(steps)
        pts.append(((t - 0.5) * length, math.sin(t * math.pi) * width * 0.5))
    for i in range(steps - 1, 0, -1):
        t = i / float(steps)
        pts.append(((t - 0.5) * length, -math.sin(t * math.pi) * width * 0.5))
    return pts


def place(pts, center, angle=0.0, scale=(1.0, 1.0)):
    ca, sa = math.cos(angle), math.sin(angle)
    out = []
    for p in pts:
        x, y = p[0] * scale[0], p[1] * scale[1]
        out.append((center[0] + x * ca - y * sa, center[1] + x * sa + y * ca))
    return out


def leaf(name, center, length, width, a0, a1, material, parent, angle=0.0, axis="z"):
    return prism(name, place(leaf_pts(length, width), center, angle), a0, a1,
                 material, parent, bevel=0.004, axis=axis)


def lobed_pts(radius, lobes, amp, steps=64, phase=0.0):
    """花瓣/云头轮廓：r = radius * (1 + amp*cos(lobes*θ))。三级板的内板用它。"""
    pts = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        r = radius * (1.0 + amp * math.cos(lobes * a + phase))
        pts.append((math.cos(a) * r, math.sin(a) * r))
    return pts


def arrow_pts(length, width, head, head_w):
    """朝 +Y 的箭头轮廓，逆时针。"""
    hw = width * 0.5
    hh = head_w * 0.5
    L = length * 0.5
    return [(-hw, -L), (hw, -L), (hw, L - head), (hh, L - head),
            (0.0, L), (-hh, L - head), (-hw, L - head)]


def ring(name, parent, outer, inner, z0, z1, material, bevel=0.008, center=(0, 0)):
    """方环：四条边框拼成。石缘和金框都用它。"""
    t = outer - inner
    cz = (z0 + z1) * 0.5
    h = z1 - z0
    cx0, cy0 = center
    for i, (cx, cy, sx, sy) in enumerate((
            (0, outer - t * 0.5, outer * 2, t),
            (0, -(outer - t * 0.5), outer * 2, t),
            (outer - t * 0.5, 0, t, inner * 2),
            (-(outer - t * 0.5), 0, t, inner * 2))):
        box("%s%d" % (name, i), (cx0 + cx, cy0 + cy, cz), (sx, sy, h), material, parent, bevel)


def bolts(name, parent, r, z, material, size=0.052):
    """角铆钉：八边形小柱 + 一层收口，参考图里四角各一颗。"""
    for i, (cx, cy) in enumerate(((r, r), (-r, r), (r, -r), (-r, -r))):
        cyl("%s%d" % (name, i), (cx, cy, z), size, 0.06, material, parent,
            sides=8, rot_z=math.radians(22.5))
        cyl("%sT%d" % (name, i), (cx, cy, z + 0.042), size * 0.70, 0.035, material, parent,
            sides=8, rot_z=math.radians(22.5))


# ----------------------------------------------------------------- 共用的边框

# 半尺寸：外缘 0.50 -> 石缘 -> 金框 -> 内区 0.345
R_OUT = 0.50
R_STONE = 0.445
R_GOLD = 0.345


def floor_frame(frame):
    """地面板共用的边框：外圈石缘 + 金色方框 + 四角铆钉 + 暗色内底。
    等级越高金框越厚，参考图里就是这么区分的。"""
    t = _tier
    ring("Kerb", frame, R_OUT, R_STONE, 0.0, 0.085, "board_stone")
    gold_h = 0.105 + 0.015 * (t - 1)
    ring("Gold", frame, R_STONE, R_GOLD, 0.0, gold_h, "board_gold")
    if t >= 2:
        # 金框内侧压一道暗金细线，边框看着更厚重
        ring("GoldLine", frame, R_GOLD + 0.020, R_GOLD, 0.0, gold_h + 0.014, "board_gold_dark")
    bolts("Bolt", frame, R_STONE - 0.042, gold_h - 0.015, "board_gold",
          size=0.050 + 0.007 * (t - 1))
    # 内底：凹下去的暗板，活动件抬起来时露出来的就是它
    box("Bed", (0, 0, 0.025), (R_GOLD * 2, R_GOLD * 2, 0.05), "board_socket", frame)


def corner_leaves(parent, a0, a1, r, length, count, axis="z", phase=math.pi * 0.25):
    """四角（或八向）的叶片点缀，数量随等级增加。"""
    for i in range(count):
        a = phase + 2 * math.pi * i / count
        leaf("Leaf%d" % i, (math.cos(a) * r, math.sin(a) * r), length, length * 0.40,
             a0, a1, "board_gold", parent, angle=a + math.pi * 0.5, axis=axis)


# ----------------------------------------------------------------- 三种面板

def build_spring(root):
    """弹簧板：铰链边一排弹簧，板面一个朝前的箭头，踩到往 +Y 掀。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    hinge_y = -R_GOLD + 0.045
    mover = joint("Mover", (0, hinge_y, 0.085), root)    # 原点就是铰链，直接绕它转
    floor_frame(frame)

    # 铰链边的弹簧：一排发光短柱，参考图里是靠一条边的那排
    n = 4 + t
    span = 0.56
    for i in range(n):
        x = (i - (n - 1) / 2.0) * (span / n)
        cyl("Coil%d" % i, (x, hinge_y, 0.085), 0.040, span / n * 0.78,
            "board_accent", frame, axis="x", sides=10)
    cyl("Rod", (0, hinge_y, 0.085), 0.021, 0.66, "board_gold_dark", frame, axis="x", sides=10)

    # 板本体：一级方板，三级换成花瓣云头板。留出边距，别把金框盖住
    depth = (R_GOLD - 0.045) - hinge_y      # 铰链到对边的距离
    cy = depth * 0.5
    if t >= 3:
        prism("PlateEdge", place(lobed_pts(0.315, 4, 0.11, phase=math.pi * 0.25), (0, cy)),
              0.0, 0.038, "board_gold", mover)
        prism("Plate", place(lobed_pts(0.285, 4, 0.11, phase=math.pi * 0.25), (0, cy)),
              0.02, 0.055, "board_stone", mover)
    else:
        w = 0.60
        box("Plate", (0, cy, 0.028), (w, depth - 0.02, 0.056),
            "board_stone_mid" if t == 1 else "board_stone", mover)
        ring("PlateEdge", mover, 0.312, 0.286, 0.0, 0.048,
             "board_gold" if t >= 2 else "board_gold_dark", center=(0, cy))

    # 箭头：指着 +Y，告诉玩家往哪边弹
    prism("Arrow", place(arrow_pts(0.40, 0.115, 0.13, 0.235), (0, cy)),
          0.055, 0.092, "board_accent", mover)
    if t >= 2:
        corner_leaves(mover, 0.056, 0.082, 0.245, 0.135, 2 if t == 2 else 4)
        for o in bpy.data.objects:
            if o.name.startswith("Leaf"):
                o.location.y += cy
    return root


def build_spikes(root):
    """尖刺板：四根刺从凹槽里升起。等级越高凹槽越花，一级方槽、二级起花瓣槽。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)
    floor_frame(frame)

    d = 0.155          # 四根刺的中心距
    for i, (sx, sy) in enumerate(((d, d), (-d, d), (d, -d), (-d, -d))):
        if t == 1:
            box("SocketLip%d" % i, (sx, sy, 0.058), (0.262, 0.262, 0.045),
                "board_gold_dark", frame)
            box("Socket%d" % i, (sx, sy, 0.062), (0.216, 0.216, 0.045), "board_socket", frame)
        else:
            a = math.atan2(sy, sx)
            prism("SocketLip%d" % i, place(lobed_pts(0.152, 2, 0.40, phase=-2 * a), (sx, sy)),
                  0.035, 0.062, "board_gold" if t >= 3 else "board_gold_dark", frame)
            prism("Socket%d" % i, place(lobed_pts(0.126, 2, 0.40, phase=-2 * a), (sx, sy)),
                  0.04, 0.078, "board_socket", frame)
    if t >= 2:
        corner_leaves(frame, 0.086, 0.112, 0.283, 0.15, 4 if t == 2 else 8, phase=0.0)
    if t >= 3:
        # 三级：中间再压一朵金花，参考图里三级花纹最密
        prism("Rosette", lobed_pts(0.088, 4, 0.32), 0.05, 0.088, "board_gold", frame)

    # 活动件：四根刺 + 托板，收回去时整体沉下去
    box("SpikeBed", (0, 0, 0.022), (0.54, 0.54, 0.044), "board_gold_dark", mover)
    for i, (sx, sy) in enumerate(((d, d), (-d, d), (d, -d), (-d, -d))):
        pyramid("Spike%d" % i, (sx, sy, 0.044), 0.185, 0.235, "board_accent", mover)
    return root


def build_push(root):
    """推板：墙面，**宽高比 2:1**。原点在墙面上，中间那块板往 +Y 推出去。
    轮廓全部建在 XZ 平面、沿 Y 挤出（prism/gem 的 axis='y'），
    免得建完再转 90 度 —— 转出来的位移极难对齐。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)

    # 2:1 —— 宽 1.0（x ±0.5），高 0.5（z 0.25~0.75）
    z0, z1 = 0.25, 0.75
    cz = (z0 + z1) * 0.5
    hw = 0.485
    hh = (z1 - z0) * 0.5

    # 贴墙的石底板：不然整块板浮在墙前面
    box("Back", (0, 0.018, cz), (hw * 2 + 0.03, 0.036, hh * 2 + 0.03), "board_stone", frame)

    # 金色外框
    fw = 0.078 + 0.012 * (t - 1)
    for nm, bx, bz, sx, sz in (("T", 0, cz + hh - fw * 0.5, hw * 2, fw),
                               ("B", 0, cz - hh + fw * 0.5, hw * 2, fw),
                               ("L", -hw + fw * 0.5, cz, fw, hh * 2 - fw * 2),
                               ("R", hw - fw * 0.5, cz, fw, hh * 2 - fw * 2)):
        box("Frame" + nm, (bx, 0.055, bz), (sx, 0.11, sz), "board_gold", frame)
    if t >= 2:
        for nm, bz in (("T", cz + hh - fw - 0.010), ("B", cz - hh + fw + 0.010)):
            box("Line" + nm, (0, 0.062, bz), (hw * 2 - fw * 2, 0.115, 0.018),
                "board_gold_dark", frame)

    # 四角铆钉（墙面板的铆钉沿 y 轴立着）
    for i, (bx, bz) in enumerate(((hw - fw * 0.5, cz + hh - fw * 0.5),
                                 (-hw + fw * 0.5, cz + hh - fw * 0.5),
                                 (hw - fw * 0.5, cz - hh + fw * 0.5),
                                 (-hw + fw * 0.5, cz - hh + fw * 0.5))):
        cyl("Bolt%d" % i, (bx, 0.115, bz), 0.050 + 0.007 * (t - 1), 0.055, "board_gold", frame,
            axis="y", sides=8, rot_z=math.radians(22.5))
        cyl("BoltT%d" % i, (bx, 0.145, bz), 0.036 + 0.005 * (t - 1), 0.03, "board_gold", frame,
            axis="y", sides=8, rot_z=math.radians(22.5))

    # 左右两条发光竖条：参考图里推板最显眼的等级标识
    bar_x = hw - fw - 0.030
    for i, sx in enumerate((-1, 1)):
        box("Bar%d" % i, (sx * bar_x, 0.085, cz), (0.052, 0.085, hh * 2 - fw * 2 - 0.035),
            "board_accent", frame)

    # 活动件：中间那块板 + 宝石
    pw = (bar_x - 0.052) * 2 - 0.02
    ph = hh * 2 - fw * 2 - 0.03
    if t >= 3:
        sc = (pw * 0.5 / 0.33, ph * 0.5 / 0.33)
        prism("PanelEdge", place(lobed_pts(0.33, 4, 0.10, phase=math.pi * 0.25), (0, cz),
                                 scale=sc), 0.02, 0.125, "board_gold", mover, axis="y")
        prism("Panel", place(lobed_pts(0.295, 4, 0.10, phase=math.pi * 0.25), (0, cz),
                             scale=sc), 0.045, 0.145, "board_stone", mover, axis="y")
    else:
        if t == 2:
            # 描边要比面板大一圈、浅一点，不然就是一块实心板把面板盖住
            box("PanelEdge", (0, 0.072, cz), (pw + 0.035, 0.085, ph + 0.035),
                "board_gold_dark", mover)
        box("Panel", (0, 0.088, cz), (pw, 0.115, ph),
            "board_stone_mid" if t == 1 else "board_stone", mover)

    gem("Gem", (0, 0.132, cz), 0.105 + 0.024 * (t - 1), 0.038 + 0.011 * (t - 1),
        0.062, "board_accent", mover, axis="y")
    if t >= 2:
        for i, sx in enumerate((-1, 1)):
            leaf("PanelLeaf%d" % i, (sx * 0.215, cz), 0.155, 0.066, 0.128, 0.155,
                 "board_gold", mover, angle=math.radians(-26 * sx), axis="y")
    return root


BUILDERS = {"spring": build_spring, "spikes": build_spikes, "push": build_push}


# ----------------------------------------------------------------- 导出与预览

def export(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(path), export_format="GLB",
                              export_apply=True, export_yup=True, use_selection=True,
                              export_materials="EXPORT", export_animations=False,
                              export_skins=False)
    print("EXPORTED %s" % os.path.abspath(path))


def render_preview(path, wall):
    from mathutils import Vector
    scene = bpy.context.scene
    w = bpy.data.worlds.new("W")
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = to_linear((0.80, 0.88, 0.94))
    bg.inputs["Strength"].default_value = 0.85

    target = (0, 0.08, 0.50) if wall else (0, 0, 0.10)
    cd = bpy.data.cameras.new("Cam")
    cd.type = "ORTHO"
    cd.ortho_scale = 1.30 if wall else 1.22
    cam = bpy.data.objects.new("Cam", cd)
    # 视角要和参考图对上，两类板子的相机在不同象限：
    #   地面板 (+x,-y)：+Y 在画面上是右上，箭头方向和参考图一致
    #   墙面板 (-x,+y)：板子朝 +Y，相机必须在 +Y 那侧，否则拍到的是背面
    #                   （第一版就是这么拍出一排空框的）
    cam.location = (-1.55, 1.55, 1.30) if wall else (1.5, -1.5, 1.6)
    d = (Vector(target) - Vector(cam.location)).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    sl = bpy.data.lights.new("Sun", type="SUN")
    sl.energy = 3.2
    sl.angle = math.radians(14)
    s = bpy.data.objects.new("Sun", sl)
    s.rotation_euler = (math.radians(50), 0, math.radians(-125))
    scene.collection.objects.link(s)

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 460
    scene.render.resolution_y = 460
    scene.render.image_settings.file_format = "PNG"
    if hasattr(scene, "view_settings"):
        scene.view_settings.view_transform = "Standard"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    print("RENDERED %s" % os.path.abspath(path))


def arg(name, default=None):
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name in a:
        i = a.index(name)
        if i + 1 < len(a):
            return a[i + 1]
    return default


def build_one(variant, tier, out_path, render_dir):
    global _tier
    _tier = tier
    clear()
    root = joint("Root", (0, 0, 0))
    BUILDERS[variant](root)
    export(out_path)
    if render_dir:
        render_preview(os.path.join(render_dir, "board_%s_%d.png" % (variant, tier)),
                       wall=(variant == "push"))


def main():
    variant = arg("--variant")
    tier = arg("--tier")
    out = arg("--out", "assets/models")
    render_dir = arg("--render-dir")

    variants = [variant] if variant else VARIANTS
    tiers = [int(tier)] if tier else TIERS
    single = variant is not None and tier is not None and out.lower().endswith(".glb")

    for v in variants:
        if v not in BUILDERS:
            print("未知面板类型：%s（可选 %s）" % (v, "/".join(VARIANTS)))
            sys.exit(1)
        for t in tiers:
            path = out if single else os.path.join(out, "board_%s_%d.glb" % (v, t))
            build_one(v, t, path, render_dir)


if __name__ == "__main__":
    main()
