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
import io
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
    # 这里写的是**贴图色**，不是最终屏幕上的颜色。游戏场景的环境光很亮，
    # 实测屏幕值 ≈ 0.31 + 0.71 * 贴图色（两点拟合），也就是说存在一个 0.31 的
    # 亮度地板 —— 按设计图直接填 0.23 的槽色，上屏是 0.475，完全不暗。
    # 所以这些值是**反推**出来的：目标屏幕值代入上式求贴图色。
    #   石材 -> 屏幕 0.95    内板 -> 屏幕 0.85（比地面略灰）
    #   槽色 -> 尽量压到地板附近   金 -> 屏幕 0.88
    "board_stone":     (0.92, 0.90, 0.87),
    "board_plate":     (0.750, 0.722, 0.690),
    "board_recess":    (0.075, 0.105, 0.130),
    "board_gold":      (0.790, 0.600, 0.330),
    "board_gold_dark": (0.34, 0.25, 0.14),
    "board_accent":    (1.0, 1.0, 1.0),      # 运行时按等级替换
}

# =====================================================================
#  可调参数表 —— 改外观形状只改这里，下面的几何代码不用动
# =====================================================================
#
# 单位一律是「格」：1.0 = 一个格子的边长（游戏里 cell_size = 2 米），
#   所以 0.05 = 10 厘米。板子按 1×1 格建，x/y 取值范围 ±0.5。
# 高度：z = 0 是地面。墙面板的 y = 0 是墙面，+Y 是伸出方向。
# 带 _step 的表示「每升一级加多少」：二级 = 基准 + step，三级 = 基准 + 2×step。
#
# 改完看效果（10 秒左右，会出一张带部件名标注的图）：
#   python tools/preview_board.py spikes 1
#
# 部件名和这张表的对应关系见 docs/机关面板_部件说明.md。

PARAMS = {

    # ---------------- 三种板共用的外框（floor_frame）----------------
    # 从外到内的层次：石缘 Kerb -> 金框 Gold -> 暗凹槽 Groove -> 内板
    "frame": {
        # 没有石缘（Kerb）—— 板子直接坐在地面上，金框外沿就是格子边
        "gold_outer":       0.500,  # 金框外沿 = 半个格子，正好顶到格子边，别超
        "gold_inner":       0.400,  # 金框内沿；两者之差 = 金框宽度（现 0.100）
        "gold_top":         0.078,  # 金框高度（一级）
        "gold_top_step":    0.008,  # 每级加高多少
        "groove_width":     0.030,  # 金框内侧那圈暗凹槽的宽度。
                                    # 它负责把金框和内板分开，去掉的话整块板会糊成一片
        "groove_below":     0.014,  # 凹槽底面比内板低多少
        "goldline_width":   0.016,  # 二级起，金框外侧那道暗金细线的宽度

        # 四角铆钉：正方形，外沿和金框外沿齐平（也就是正好占住格子的四个角）
        "bolt_size":        0.155,  # 正方形边长（一级）
        "bolt_size_step":   0.008,  # 每级加大多少
        "bolt_cut":         0.3333, # 朝格子内侧那个角切斜角，下刀在两条边的这个比例处
        "bolt_body_h":      0.098,  # 铆钉主体高度（比金框略高，才看得出是颗钉）
        "bolt_cap_h":       0.028,  # 顶上那层收口的高度
        "bolt_cap_scale":   0.72,   # 收口相对主体缩小多少（外角仍贴着格子边）
        "plate_top":        0.062,  # 内板上表面。**所有活动件静止时都对齐到这个高度**
    },

    # ---------------- 尖刺板 ----------------
    # 内板做成「井」字：外圈 Plate + 十字隔条 PlateCross，中间空出四个方槽。
    # 槽壁贴暗色内衬 Liner，槽底是砖体 Base 的顶面。
    "spikes": {
        "base_depth":       0.300,  # 砖体往地下的厚度。刺收回去要能整根藏进去
        "plate_inset":      0.030,  # 内板外沿从 gold_inner 再往里缩多少（让开暗凹槽）
        "plate_rim":        0.030,  # 内板外圈的宽度
        "cross_half":       0.048,  # 十字隔条的半宽
        "liner_width":      0.028,  # 槽壁暗色内衬的厚度
        "cap_fill":         0.60,   # 锥体宽度 ÷ 槽口宽度。
                                    # 给到 0.8 会把槽底的深色全盖住，看着就是四块平方片
        "shaft_fill":       0.80,   # 刺杆宽度 ÷ 锥体底宽
        "shaft_len":        0.220,  # 刺杆长度，决定弹出来以后刺有多长
        "tip_below_plate":  0.002,  # 静止时刺尖比内板低多少。保证「不突出」
    },

    # ---------------- 弹簧板 ----------------
    # 弹出侧（-Y）有一条结构：深槽 Channel + 发光条 Glow + 两端螺栓 ChBolt。
    # 板子 Plate 绕这条结构的外沿翻起，箭头 Arrow 平嵌在板面里。
    "spring": {
        "channel_from_edge": 0.080, # 结构条中心离内区边缘多远
        "channel_w":        0.600,  # 深槽宽度（x 向）
        "channel_d":        0.150,  # 深槽进深（y 向）
        "channel_h":        0.052,  # 深槽高度
        "glow_w":           0.520,  # 发光条尺寸
        "glow_d":           0.072,
        "glow_h":           0.030,
        "glow_z":           0.048,  # 发光条中心高度
        "chbolt_x":         0.325,  # 两端螺栓的 x 位置
        "chbolt_r":         0.074,  # 深槽两端螺栓的半径
        "chbolt_cap_r":     0.053,  # 螺栓顶上那圈收口的半径
        "hinge_offset":     0.062,  # 铰链在结构条中心外侧多远。板子绕这条线翻起
        "plate_w":          0.680,  # 板宽
        "plate_margin":     0.012,  # 板前沿离内区边缘留多少
        "plate_thick":      0.044,
        "edge_outer":       0.340,  # 板边金线（方环）的外沿
        "edge_inner":       0.318,  # 和内沿
        "arrow_len":        0.500,  # 箭头总长
        "arrow_shaft_w":    0.150,  # 箭杆宽
        "arrow_head_len":   0.170,  # 箭头部分的长度
        "arrow_head_w":     0.310,  # 箭头最宽处
        "arrow_sink":       0.012,  # 箭头嵌进板面多深（只露 0.005，所以是「平嵌」）
        "leaf_len":         0.150,  # 叶片长度
        "leaf_width":       0.062,  # 叶片宽度（最宽处）
        "leaf_x":           0.215,  # 叶片离中线多远
    },

    # ---------------- 推板（墙面）----------------
    # z_top - z_bottom = 0.5，宽 ≈ 1.0，所以是 2:1。
    "push": {
        "z_bottom":         0.250,  # 面板下沿高度（墙高按 1.0 算）
        "z_top":            0.750,  # 面板上沿
        "half_w":           0.485,  # 半宽
        "frame_w":          0.062,  # 金框条宽（一级）
        "frame_w_step":     0.008,
        "front":            0.072,  # 金框正面离墙多远。**面板静止时和它齐平**
        "groove_w":         0.028,  # 金框内沿暗凹槽的宽度
        "bolt_r":           0.072,  # 四角铆钉半径（一级）
        "bolt_r_step":      0.006,
        "bolt_h":           0.058,
        "bar_w":            0.050,  # 左右发光竖条的宽度
        "bar_inset":        0.046,  # 竖条离金框内沿多远
        "gem_r":            0.130,  # 宝石外半径（一级）
        "gem_r_step":       0.022,
        "gem_inner":        0.048,  # 宝石内半径（星形的凹点）
        "gem_inner_step":   0.010,
        "gem_h":            0.058,  # 宝石凸出高度。这个是**允许**凸出的
        "leaf_len":         0.150,
        "leaf_width":       0.062,
        "leaf_x":           0.205,
    },
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
            b.inputs["Emission Strength"].default_value = 0.45
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


def bracket_pts(outer, size, cut, sx, sy):
    """一颗方形角铆钉的轮廓（逆时针）。

    正方形的外角落在 (outer, outer)，也就是格子的角上；朝格子内侧的那个角
    切掉一个斜角，下刀位置在两条边的 size*cut 处。sx/sy 是镜像到另外三个角用的。
    """
    o, sz, c = outer, size, size * cut
    pts = [(o - sz + c, o - sz),   # 斜角起点（在一条边的 1/3 处）
           (o, o - sz),            # 外侧那条边
           (o, o),                 # 外角 —— 正好是格子的角
           (o - sz, o),
           (o - sz, o - sz + c)]   # 斜角终点（在另一条边的 1/3 处）
    pts = [(x * sx, y * sy) for x, y in pts]
    if sx * sy < 0:
        pts.reverse()              # 镜像一次会把朝向翻过来，点序得倒回去
    return pts


def bolts(name, parent, outer, size, cut, body_h, cap_h, cap_scale, material):
    """四角的方形铆钉：主体 + 顶上一层收口。收口只往内缩，外角照样贴着格子边。"""
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1))):
        prism("%s%d" % (name, i), bracket_pts(outer, size, cut, sx, sy),
              0.0, body_h, material, parent, bevel=0.005)
        prism("%sT%d" % (name, i), bracket_pts(outer, size * cap_scale, cut, sx, sy),
              body_h, body_h + cap_h, material, parent, bevel=0.005)


# ----------------------------------------------------------------- 共用的边框

# 下面全部从 PARAMS 取值，不要在几何代码里再写死数字 ——
# 想调形状请改文件顶部那张表。

def fp(key):
    """取 frame 段的参数。写成函数只是为了下面读起来短一点。"""
    return PARAMS["frame"][key]


def tier_val(base, step):
    """按等级线性增长的参数：一级 = base，每升一级加 step。"""
    return base + step * (_tier - 1)


def floor_frame(frame):
    """地面板共用的边框，从外到内：

      Gold      金框，外沿直接顶到格子边（没有石缘，板子就坐在地面上）
      GoldLine  二级起金框内侧的暗金细线
      Bolt      四角的**方形**铆钉，外角贴着格子角，朝内的角切斜角
                （BoltT 是它顶上的收口）
      Groove    金框内侧的暗凹槽 —— 靠它把金框和内板分开，去掉整块板会糊成一片
    """
    gold_h = tier_val(fp("gold_top"), fp("gold_top_step"))
    ring("Gold", frame, fp("gold_outer"), fp("gold_inner"), 0.0, gold_h, "board_gold")
    ring("Groove", frame, fp("gold_inner"), fp("gold_inner") - fp("groove_width"),
         0.0, fp("plate_top") - fp("groove_below"), "board_recess")
    if _tier >= 2:
        ring("GoldLine", frame, fp("gold_inner") + fp("goldline_width"), fp("gold_inner"),
             0.0, gold_h + 0.010, "board_gold_dark")
    bolts("Bolt", frame, fp("gold_outer"),
          tier_val(fp("bolt_size"), fp("bolt_size_step")), fp("bolt_cut"),
          fp("bolt_body_h"), fp("bolt_cap_h"), fp("bolt_cap_scale"), "board_gold")


def corner_leaves(parent, a0, a1, r, length, count, axis="z", phase=math.pi * 0.25):
    """四角（或八向）的叶片点缀，数量随等级增加。"""
    for i in range(count):
        a = phase + 2 * math.pi * i / count
        leaf("Leaf%d" % i, (math.cos(a) * r, math.sin(a) * r), length, length * 0.40,
             a0, a1, "board_gold", parent, angle=a + math.pi * 0.5, axis=axis)


# ----------------------------------------------------------------- 三种面板

def build_spring(root):
    """弹簧板。部件：

      固定（Frame）  Kerb / Gold / Groove / Bolt  外框
                     Channel  弹出侧的深槽
                     Glow     深槽里的发光条（等级色）
                     ChBolt   深槽两端的大螺栓
      活动（Mover）  Plate      板本体，绕深槽外沿翻起
                     PlateEdge  板边一圈金线
                     Arrow      平嵌在板面里的箭头（等级色）
                     Leaf       板面上的叶片

    静止时 Plate 上表面和内板齐平，Arrow 只比板面高 0.005，所以是「平嵌」。
    """
    P = PARAMS["spring"]
    frame = joint("Frame", (0, 0, 0), root)
    floor_frame(frame)

    # 弹出侧（-Y）的结构：深槽 + 发光条 + 两端螺栓。
    # 设计图里这条又粗又显眼，是弹簧板最好认的特征，说明这一侧是铰链、往对面弹。
    ch_y = -fp("gold_inner") + P["channel_from_edge"]
    box("Channel", (0, ch_y, P["channel_h"] * 0.5),
        (P["channel_w"], P["channel_d"], P["channel_h"]), "board_recess", frame)
    box("Glow", (0, ch_y, P["glow_z"]), (P["glow_w"], P["glow_d"], P["glow_h"]),
        "board_accent", frame)
    for i, sx in enumerate((-1, 1)):
        cyl("ChBolt%d" % i, (sx * P["chbolt_x"], ch_y, 0.050), P["chbolt_r"], 0.070,
            "board_gold", frame, sides=8, rot_z=math.radians(22.5))
        cyl("ChBoltT%d" % i, (sx * P["chbolt_x"], ch_y, 0.090), P["chbolt_cap_r"], 0.030,
            "board_gold", frame, sides=8, rot_z=math.radians(22.5))

    # 板本体：铰链在深槽外沿，静止时上表面和内板齐平
    hinge_y = ch_y + P["hinge_offset"]
    mover = joint("Mover", (0, hinge_y, 0.0), root)
    depth = fp("gold_inner") - P["plate_margin"] - hinge_y
    cy = depth * 0.5
    top = fp("plate_top")
    box("Plate", (0, cy, top - P["plate_thick"] * 0.5), (P["plate_w"], depth, P["plate_thick"]),
        "board_plate", mover)
    ring("PlateEdge", mover, P["edge_outer"], P["edge_inner"], top - 0.030, top + 0.003,
         "board_gold" if _tier >= 2 else "board_gold_dark", center=(0, cy))

    prism("Arrow", place(arrow_pts(P["arrow_len"], P["arrow_shaft_w"],
                                   P["arrow_head_len"], P["arrow_head_w"]), (0, cy)),
          top - P["arrow_sink"], top + 0.005, "board_accent", mover, bevel=0.004)
    # 叶片也是平嵌的。设计图里一级就有两片，三级再加两片
    for i, sx in enumerate((-1, 1)):
        leaf("Leaf%d" % i, (sx * P["leaf_x"], cy + 0.115 * sx), P["leaf_len"],
             P["leaf_width"], top - 0.008, top + 0.003, "board_gold", mover,
             angle=math.radians(-30 * sx))
    if _tier >= 3:
        for i, sx in enumerate((-1, 1)):
            leaf("Leaf%d" % (i + 2), (sx * (P["leaf_x"] + 0.030), cy - 0.20),
                 0.130, 0.054, top - 0.008, top + 0.003,
                 "board_gold", mover, angle=math.radians(30 * sx))
    return root


def build_spikes(root):
    """尖刺板。部件：

      固定（Frame）  Kerb / Gold / Groove / Bolt  外框
                     Base        砖体，实心，顶面就是槽底
                     Plate       浅灰内板的外圈
                     PlateCrossX/Y  十字隔条，和外圈一起围出四个方槽
                     Liner       槽壁的暗色内衬（只有槽底暗的话看不出深度）
      活动（Mover）  Spike       锥体刺尖（等级色）
                     SpikeShaft  刺杆，静止时整根藏在砖体里

    三个等级槽形完全一样，只有刺的颜色不同。
    静止姿态就是导出的姿态：刺尖比板面低 tip_below_plate，不突出。
    """
    P = PARAMS["spikes"]
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)
    floor_frame(frame)

    inner = fp("gold_inner") - P["plate_inset"]
    top = fp("plate_top")
    # 砖体按**金框内沿**铺满，不是按内板外沿 —— 要连凹槽底下也垫上
    box("Base", (0, 0, -P["base_depth"] * 0.5),
        (fp("gold_inner") * 2, fp("gold_inner") * 2, P["base_depth"]), "board_recess", frame)

    div = P["cross_half"]
    rim = P["plate_rim"]
    cz, h = top * 0.5, top
    ring("Plate", frame, inner, inner - rim, 0.0, top, "board_plate")
    box("PlateCrossX", (0, 0, cz), (inner * 2, div * 2, h), "board_plate", frame)
    box("PlateCrossY", (0, 0, cz), (div * 2, inner * 2, h), "board_plate", frame)

    hole_w = (inner - rim) - div     # 一个方槽的**全宽**
    d = div + hole_w * 0.5           # 槽中心距原点
    hw = hole_w * 0.5
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1))):
        ring("Liner%d" % i, frame, hw, hw - P["liner_width"], 0.0, top, "board_recess",
             center=(d * sx, d * sy))

    cap_w = hole_w * P["cap_fill"]
    tip = top - P["tip_below_plate"]
    cap_h = tip - 0.004              # 锥底落在槽底
    base_z = tip - cap_h
    for i, (sx, sy) in enumerate(((d, d), (-d, d), (d, -d), (-d, -d))):
        box("SpikeShaft%d" % i, (sx, sy, base_z - P["shaft_len"] * 0.5 + 0.004),
            (cap_w * P["shaft_fill"], cap_w * P["shaft_fill"], P["shaft_len"]),
            "board_accent", mover)
        pyramid("Spike%d" % i, (sx, sy, base_z), cap_w, cap_h, "board_accent", mover)
    return root


def build_push(root):
    """推板（墙面，2:1）。部件：

      固定（Frame）  Back        贴墙的石底板
                     FrameT/B/L/R  金框四条边
                     LineT/B     二级起金框上下的暗金细线
                     Bolt        四角铆钉
                     GrooveT/B/L/R  金框内沿的暗凹槽
                     Bar         左右两条发光竖条（等级色）
      活动（Mover）  Panel       中间的浅灰面板，静止时正面和金框齐平
                     PanelEdge   二级起面板外的一圈描边
                     Gem         面板中央的宝石（等级色，允许凸出）
                     PanelLeaf   面板上的叶片

    轮廓建在 XZ 平面沿 Y 挤出（prism/gem 的 axis='y'），免得建完再转 90 度。
    """
    P = PARAMS["push"]
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)

    z0, z1 = P["z_bottom"], P["z_top"]
    cz = (z0 + z1) * 0.5
    hw = P["half_w"]
    hh = (z1 - z0) * 0.5
    front = P["front"]

    box("Back", (0, 0.014, cz), (hw * 2 + 0.03, 0.028, hh * 2 + 0.03), "board_stone", frame)

    fw = tier_val(P["frame_w"], P["frame_w_step"])
    for nm, bx, bz, sx, sz in (("T", 0, cz + hh - fw * 0.5, hw * 2, fw),
                               ("B", 0, cz - hh + fw * 0.5, hw * 2, fw),
                               ("L", -hw + fw * 0.5, cz, fw, hh * 2 - fw * 2),
                               ("R", hw - fw * 0.5, cz, fw, hh * 2 - fw * 2)):
        box("Frame" + nm, (bx, front * 0.5, bz), (sx, front, sz), "board_gold", frame)
    if _tier >= 2:
        for nm, bz in (("T", cz + hh - fw - 0.008), ("B", cz - hh + fw + 0.008)):
            box("Line" + nm, (0, front * 0.55, bz), (hw * 2 - fw * 2, front * 1.05, 0.014),
                "board_gold_dark", frame)

    for i, (bx, bz) in enumerate(((hw - fw * 0.5, cz + hh - fw * 0.5),
                                 (-hw + fw * 0.5, cz + hh - fw * 0.5),
                                 (hw - fw * 0.5, cz - hh + fw * 0.5),
                                 (-hw + fw * 0.5, cz - hh + fw * 0.5))):
        cyl("Bolt%d" % i, (bx, front + 0.022, bz), tier_val(P["bolt_r"], P["bolt_r_step"]),
            P["bolt_h"], "board_gold", frame, axis="y", sides=8, rot_z=math.radians(22.5))

    gw = P["groove_w"]
    for nm, bx, bz, sx, sz in (("T", 0, cz + hh - fw - gw * 0.5, hw * 2 - fw * 2, gw),
                               ("B", 0, cz - hh + fw + gw * 0.5, hw * 2 - fw * 2, gw),
                               ("L", -hw + fw + gw * 0.5, cz, gw, hh * 2 - fw * 2),
                               ("R", hw - fw - gw * 0.5, cz, gw, hh * 2 - fw * 2)):
        box("Groove" + nm, (bx, front * 0.42, bz), (sx, front * 0.84, sz),
            "board_recess", frame)

    bar_x = hw - fw - P["bar_inset"]
    for i, sx in enumerate((-1, 1)):
        box("Bar%d" % i, (sx * bar_x, front * 0.62, cz),
            (P["bar_w"], front * 0.80, hh * 2 - fw * 2 - 0.030), "board_accent", frame)

    pw = (bar_x - P["bar_w"]) * 2 - 0.018
    ph = hh * 2 - fw * 2 - 0.026
    box("Panel", (0, front * 0.5 + 0.008, cz), (pw, front - 0.016, ph), "board_plate", mover)
    if _tier >= 2:
        box("PanelEdge", (0, front * 0.5 - 0.004, cz), (pw + 0.030, front - 0.020, ph + 0.030),
            "board_gold_dark" if _tier == 2 else "board_gold", mover)

    gem("Gem", (0, front + 0.004, cz), tier_val(P["gem_r"], P["gem_r_step"]),
        tier_val(P["gem_inner"], P["gem_inner_step"]), P["gem_h"], "board_accent",
        mover, axis="y")
    if _tier >= 2:
        for i, sx in enumerate((-1, 1)):
            leaf("PanelLeaf%d" % i, (sx * P["leaf_x"], cz), P["leaf_len"],
                 P["leaf_width"], front - 0.010, front + 0.006, "board_gold", mover,
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


def render_preview(path, wall, res=460):
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
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.image_settings.file_format = "PNG"
    if hasattr(scene, "view_settings"):
        scene.view_settings.view_transform = "Standard"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    print("RENDERED %s" % os.path.abspath(path))


def dump_part_map(path, res):
    """把每个部件在预览图上的位置导出来，给 tools/preview_board.py 画标注。

    同名部件（Bolt0..3 这种）合并成一组，取离相机最近的那一个当标注点 ——
    四颗铆钉标四次没意义，标最显眼的那颗就够了。"""
    import json
    import bpy_extras.object_utils as ou
    from mathutils import Vector

    scene = bpy.context.scene
    cam = scene.camera
    parts = {}
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        c = Vector((0, 0, 0))
        for v in ob.bound_box:
            c += ob.matrix_world @ Vector(v)
        c /= 8.0
        co = ou.world_to_camera_view(scene, cam, c)
        # 往上找 Frame / Mover，标出这个部件是固定的还是活动的
        grp, n = "Frame", ob
        while n is not None:
            if n.name in ("Frame", "Mover"):
                grp = n.name
                break
            n = n.parent
        base = ob.name.rstrip("0123456789") or ob.name
        rec = parts.get(base)
        if rec is None or co.z < rec["depth"]:
            parts[base] = {"x": co.x, "y": co.y, "depth": co.z, "group": grp}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"res": res, "parts": parts}, ensure_ascii=False, indent=1))
    print("PARTMAP %s" % os.path.abspath(path))


def arg(name, default=None):
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name in a:
        i = a.index(name)
        if i + 1 < len(a):
            return a[i + 1]
    return default


def build_one(variant, tier, out_path, render_dir, part_map_dir=None):
    global _tier
    _tier = tier
    clear()
    root = joint("Root", (0, 0, 0))
    BUILDERS[variant](root)
    export(out_path)
    res = 760 if part_map_dir else 460
    target_dir = part_map_dir or render_dir
    if target_dir:
        render_preview(os.path.join(target_dir, "board_%s_%d.png" % (variant, tier)),
                       wall=(variant == "push"), res=res)
    if part_map_dir:
        dump_part_map(os.path.join(part_map_dir, "board_%s_%d.json" % (variant, tier)), res)


def main():
    variant = arg("--variant")
    tier = arg("--tier")
    out = arg("--out", "assets/models")
    render_dir = arg("--render-dir")
    part_map_dir = arg("--part-map")

    variants = [variant] if variant else VARIANTS
    tiers = [int(tier)] if tier else TIERS
    single = variant is not None and tier is not None and out.lower().endswith(".glb")

    for v in variants:
        if v not in BUILDERS:
            print("未知面板类型：%s（可选 %s）" % (v, "/".join(VARIANTS)))
            sys.exit(1)
        for t in tiers:
            path = out if single else os.path.join(out, "board_%s_%d.glb" % (v, t))
            build_one(v, t, path, render_dir, part_map_dir)


if __name__ == "__main__":
    main()
