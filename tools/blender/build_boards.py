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

# 以下都按 sRGB 写（直接在参考图上吸的色），用的时候转线性。
# 内板和槽底是这一版改动最大的地方：原来给成了接近黑，参考图里其实
# 只比地砖略灰一点，槽底也只是中灰。
COLORS = {
    "board_stone":     (0.97, 0.96, 0.93),   # 奶白石材，和场景地面一个调子
    "board_plate":     (0.845, 0.815, 0.781),  # 内板：比地面略灰一点
    "board_recess":    (0.40, 0.43, 0.44),   # 槽底/凹槽：中灰，不是黑
    "board_gold":      (0.85, 0.68, 0.28),
    "board_gold_dark": (0.58, 0.45, 0.22),
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
    b.inputs["Roughness"].default_value = 0.38 if name == "board_gold" else (
        0.48 if name == "board_accent" else 0.82)
    if "Metallic" in b.inputs:
        # 金属度别给高：Godot 那边只有环境色、没有反射探针，metallic 0.85 的金
        # 直接渲成暗褐色。0.3 在 Blender 预览和游戏里都还是金色。
        b.inputs["Metallic"].default_value = 0.30 if name.startswith("board_gold") else 0.0
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
        cyl("%s%d" % (name, i), (cx, cy, z), size, 0.055, material, parent,
            sides=8, rot_z=math.radians(22.5))
        cyl("%sT%d" % (name, i), (cx, cy, z + 0.032), size * 0.70, 0.026, material, parent,
            sides=8, rot_z=math.radians(22.5))


# ----------------------------------------------------------------- 共用的边框

# 半尺寸：外缘 0.50 -> 石缘 -> 金框 -> 内区 0.400
# 参考图里边框很薄、整体很平，所以这一版比第一版矮了一半还多。
R_OUT = 0.50
R_STONE = 0.455
R_GOLD = 0.400

PLATE_TOP = 0.062       # 内板上表面：活动件静止时都要和它齐平
FRAME_TOP = 0.078       # 金框上表面，只比内板高一点点


def floor_frame(frame):
    """地面板共用的边框：外圈石缘 + 薄金框 + 四角铆钉。等级越高金框略厚。"""
    t = _tier
    ring("Kerb", frame, R_OUT, R_STONE, 0.0, 0.050, "board_stone")
    gold_h = FRAME_TOP + 0.008 * (t - 1)
    ring("Gold", frame, R_STONE, R_GOLD, 0.0, gold_h, "board_gold")
    if t >= 2:
        ring("GoldLine", frame, R_GOLD + 0.016, R_GOLD, 0.0, gold_h + 0.010, "board_gold_dark")
    bolts("Bolt", frame, R_STONE - 0.030, gold_h - 0.020, "board_gold",
          size=0.052 + 0.005 * (t - 1))


def corner_leaves(parent, a0, a1, r, length, count, axis="z", phase=math.pi * 0.25):
    """四角（或八向）的叶片点缀，数量随等级增加。"""
    for i in range(count):
        a = phase + 2 * math.pi * i / count
        leaf("Leaf%d" % i, (math.cos(a) * r, math.sin(a) * r), length, length * 0.40,
             a0, a1, "board_gold", parent, angle=a + math.pi * 0.5, axis=axis)


# ----------------------------------------------------------------- 三种面板

def build_spring(root):
    """弹簧板：弹出的那一侧边框里有结构（凹槽 + 发光条 + 两端铆钉），
    板面是浅灰的，箭头**平嵌**在板里而不是凸出来。静止时整块板和边框齐平。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    floor_frame(frame)

    # 弹出侧（-Y）的结构：一条凹槽，里面一根发光条，两端各一颗铆钉。
    # 参考图里这条是弹簧板最好认的特征，说明这一侧是铰链、往对面弹。
    ch_y = -R_GOLD + 0.058
    box("Channel", (0, ch_y, 0.030), (0.72, 0.098, 0.060), "board_recess", frame)
    box("ChannelLip", (0, ch_y, 0.020), (0.76, 0.125, 0.040), "board_gold_dark", frame)
    box("Glow", (0, ch_y, 0.052), (0.60, 0.050, 0.024), "board_accent", frame)
    for i, sx in enumerate((-1, 1)):
        cyl("ChBolt%d" % i, (sx * 0.345, ch_y, 0.050), 0.050, 0.050, "board_gold", frame,
            sides=8, rot_z=math.radians(22.5))

    # 板本体：铰链在凹槽外沿，静止时上表面和内板齐平
    hinge_y = ch_y + 0.062
    mover = joint("Mover", (0, hinge_y, 0.0), root)
    depth = R_GOLD - 0.012 - hinge_y
    cy = depth * 0.5
    box("Plate", (0, cy, PLATE_TOP - 0.022), (0.74, depth, 0.044), "board_plate", mover)
    if t >= 2:
        # 板边一圈金线，等级越高越明显
        ring("PlateEdge", mover, 0.372, 0.352, PLATE_TOP - 0.030, PLATE_TOP + 0.002,
             "board_gold" if t >= 3 else "board_gold_dark", center=(0, cy))

    # 箭头：平嵌进板面，只比板高一点点（防 z-fighting），不做成凸起
    prism("Arrow", place(arrow_pts(0.42, 0.125, 0.14, 0.255), (0, cy)),
          PLATE_TOP - 0.012, PLATE_TOP + 0.004, "board_accent", mover, bevel=0.004)
    if t >= 2:
        # 叶片也是平嵌的
        for i, sx in enumerate((-1, 1)):
            leaf("Leaf%d" % i, (sx * 0.245, cy + 0.02), 0.150, 0.062,
                 PLATE_TOP - 0.008, PLATE_TOP + 0.003, "board_gold", mover,
                 angle=math.radians(-30 * sx))
    if t >= 3:
        for i, sx in enumerate((-1, 1)):
            leaf("Leaf%d" % (i + 2), (sx * 0.245, cy - 0.20), 0.130, 0.054,
                 PLATE_TOP - 0.008, PLATE_TOP + 0.003, "board_gold", mover,
                 angle=math.radians(30 * sx))
    return root


def build_spikes(root):
    """尖刺板：浅灰内板上开四个**方槽**，槽里各一根尖刺。
    三个等级槽形完全一样，只有尖刺颜色不同（按用户要求，后两级不再加花纹）。
    静止姿态就是导出的姿态：刺尖和板面齐平，不突出。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)
    floor_frame(frame)

    # 砖体：实心，顶面就是槽底。尖刺收回去整根缩进砖体里，自然被挡住。
    # 参考图里的地砖本来就有厚度，所以这块砖体不是凭空加的。
    # 砖体要够深，收回去的刺杆整根都得藏在里面（在游戏里它本来就在地面以下）
    box("Base", (0, 0, -0.150), (R_GOLD * 2, R_GOLD * 2, 0.300), "board_recess", frame)

    # 浅灰内板做成"井"字：外圈 + 十字隔条，中间空出四个方槽
    inner = R_GOLD - 0.006
    div = 0.055                      # 十字隔条半宽
    rim = 0.048                      # 外圈宽度
    z0, z1 = 0.0, PLATE_TOP
    cz, h = (z0 + z1) * 0.5, z1 - z0
    ring("Plate", frame, inner, inner - rim, z0, z1, "board_plate")
    box("PlateCrossX", (0, 0, cz), (inner * 2, div * 2, h), "board_plate", frame)
    box("PlateCrossY", (0, 0, cz), (div * 2, inner * 2, h), "board_plate", frame)

    # 四根刺：刺尖静止时正好落在板面高度上 —— 不突出，但槽里看得见刺。
    # 锥体做得矮而宽，这样从槽口看过去填得满，和参考图一致；
    # 下面再接一段方柱，弹出来的时候才是一根像样的刺，而不是一片薄锥。
    hole_w = (inner - rim) - div     # 一个方槽的**全宽**
    d = div + hole_w * 0.5           # 槽中心距原点（之前误用了槽外沿，刺大了一倍）
    cap_h = 0.090
    cap_w = hole_w * 0.82
    tip = PLATE_TOP - 0.002          # 刺尖：刚好齐板面，确保不突出
    base_z = tip - cap_h
    shaft_h = 0.20
    # 不做托板：四根刺已经挂在 Mover 下面一起动，托板反而会露在砖体外面
    for i, (sx, sy) in enumerate(((d, d), (-d, d), (d, -d), (-d, -d))):
        box("SpikeShaft%d" % i, (sx, sy, base_z - shaft_h * 0.5 + 0.004),
            (cap_w * 0.80, cap_w * 0.80, shaft_h), "board_accent", mover)
        pyramid("Spike%d" % i, (sx, sy, base_z), cap_w, cap_h, "board_accent", mover)
    return root


def build_push(root):
    """推板：墙面，**宽高比 2:1**。静止时面板和金框正面齐平，往 +Y 推出去。
    轮廓建在 XZ 平面沿 Y 挤出（prism/gem 的 axis='y'），免得建完再转 90 度。"""
    t = _tier
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)

    # 2:1 —— 宽 1.0（x ±0.5），高 0.5（z 0.25~0.75）
    z0, z1 = 0.25, 0.75
    cz = (z0 + z1) * 0.5
    hw = 0.485
    hh = (z1 - z0) * 0.5

    # 贴墙的石底板
    box("Back", (0, 0.014, cz), (hw * 2 + 0.03, 0.028, hh * 2 + 0.03), "board_stone", frame)

    # 薄金框
    fw = 0.062 + 0.008 * (t - 1)
    front = 0.072                     # 金框正面的 y，面板静止时和它齐平
    for nm, bx, bz, sx, sz in (("T", 0, cz + hh - fw * 0.5, hw * 2, fw),
                               ("B", 0, cz - hh + fw * 0.5, hw * 2, fw),
                               ("L", -hw + fw * 0.5, cz, fw, hh * 2 - fw * 2),
                               ("R", hw - fw * 0.5, cz, fw, hh * 2 - fw * 2)):
        box("Frame" + nm, (bx, front * 0.5, bz), (sx, front, sz), "board_gold", frame)
    if t >= 2:
        for nm, bz in (("T", cz + hh - fw - 0.008), ("B", cz - hh + fw + 0.008)):
            box("Line" + nm, (0, front * 0.55, bz), (hw * 2 - fw * 2, front * 1.05, 0.014),
                "board_gold_dark", frame)

    # 四角铆钉
    for i, (bx, bz) in enumerate(((hw - fw * 0.5, cz + hh - fw * 0.5),
                                 (-hw + fw * 0.5, cz + hh - fw * 0.5),
                                 (hw - fw * 0.5, cz - hh + fw * 0.5),
                                 (-hw + fw * 0.5, cz - hh + fw * 0.5))):
        cyl("Bolt%d" % i, (bx, front + 0.018, bz), 0.052 + 0.006 * (t - 1), 0.050,
            "board_gold", frame, axis="y", sides=8, rot_z=math.radians(22.5))

    # 左右两条发光竖条，紧贴金框内沿
    bar_x = hw - fw - 0.032
    for i, sx in enumerate((-1, 1)):
        box("Bar%d" % i, (sx * bar_x, front * 0.62, cz),
            (0.050, front * 0.80, hh * 2 - fw * 2 - 0.030), "board_accent", frame)

    # 活动件：中间那块浅灰面板，正面和金框齐平
    pw = (bar_x - 0.050) * 2 - 0.018
    ph = hh * 2 - fw * 2 - 0.026
    box("Panel", (0, front * 0.5 + 0.008, cz), (pw, front - 0.016, ph), "board_plate", mover)
    if t >= 2:
        box("PanelEdge", (0, front * 0.5 - 0.004, cz), (pw + 0.030, front - 0.020, ph + 0.030),
            "board_gold_dark" if t == 2 else "board_gold", mover)

    # 宝石：这个是允许凸出来的，参考图里就是一颗嵌在板上的宝石
    gem("Gem", (0, front + 0.006, cz), 0.100 + 0.020 * (t - 1), 0.036 + 0.009 * (t - 1),
        0.050, "board_accent", mover, axis="y")
    if t >= 2:
        for i, sx in enumerate((-1, 1)):
            leaf("PanelLeaf%d" % i, (sx * 0.205, cz), 0.150, 0.062,
                 front - 0.010, front + 0.006, "board_gold", mover,
                 angle=math.radians(-26 * sx), axis="y")
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

    target = (0, 0.06, 0.50) if wall else (0, 0, 0.04)
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
