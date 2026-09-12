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
    "board_base":      (0.545, 0.520, 0.495),  # 底座：比 plate 略深一点的灰，不是黑
    # 注意：这是**棱上**的亮度。平面会被顶点色的棱高光压到约 0.62 倍，
    # 所以看上去的"金色"比这个值暗一截，别直接拿设计图吸到的中间色填这里。
    "board_gold":      (0.960, 0.790, 0.470),
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
        # 金框高度不再单独给，而是**跟着内板走**：gold_top = plate_top + 这个值。
        # 写死一个绝对高度的话，一抬 plate_top 金框就框不住叠层，
        # 底座的侧壁会直接露在金框外面（v0.0.50 就是这么出的问题）。
        "gold_above_plate": 0.014,  # 金框比内板高出多少（一级）
        "gold_above_step":  0.004,  # 每级再高多少
        "goldline_width":   0.016,  # 二级起，金框外侧那道暗金细线的宽度

        # 四角铆钉：正方形，外沿和金框外沿齐平（也就是正好占住格子的四个角）
        "bolt_size":        0.155,  # 正方形边长（一级）
        "bolt_size_step":   0.008,  # 每级加大多少
        "bolt_cut":         0.3333, # 朝格子内侧那个角切斜角，下刀在两条边的这个比例处
        "bolt_body_h":      0.049,  # 铆钉主体高度
        "bolt_bevel":       0.012,  # 铆钉的倒角。金框压矮以后铆钉只比它高一点点，
                                    # 靠这个倒角做出一圈高光/暗边，才不会和金框糊在一起
        "bolt_cap_h":       0.0187, # 顶上那颗八角钉帽的高度
        "bolt_cap_ratio":   0.3333, # 钉帽半径 ÷ bolt_size。
                                    # 上限是 0.471（正方形中心到朝内斜角的距离），
                                    # 超过就会切出斜角外面去
        "plate_top":        0.027,  # 内板上表面。**它同时是竖井的深度上限** ——
                                    # 游戏里 y=0 以下被地板挡住，井最深只能到这里。
                                    # 抬高 = 洞更深，但整块板在地面上也凸得更高，
                                    # 两者是直接矛盾的，只能取舍。
                                    # **所有活动件静止时都对齐到这个高度**
    },

    # ---------------- 顶点色 AO ----------------
    # 烘出来的原始值 1 = 完全不被遮挡，0 = 全遮住。
    # 最终顶点色 = 1 - (1 - 原始值) × strength，所以 strength 越大压得越狠。
    "ao": {
        "strength":         0.85,   # AO 强度（0 = 关掉）
        "distance":         0.060,  # 采样距离（格）。**要和零件尺度相称**：
                                    # 给到 0.18（比金框宽 0.10、高 0.039 还大好几倍）
                                    # 时，金框上每个顶点都"看到"内板和底座，
                                    # 整条被均匀压暗，和四角凸出的铆钉差出一大截 ——
                                    # 那就不是接触阴影，只是把薄零件整体调暗了
        "samples":          64,     # Cycles 采样数，够用就行，烘一块也就几秒
        "floor":            0.30,   # 最暗压到多少，防止角落烘成纯黑
        "subdiv_edge":      0.045,  # 烘之前先把长过这个值的边切开。
                                    # **这一步不能省**：顶点色只存在顶点上，一个平面
                                    # 只有四个角的话 AO 只能在整面上线性插值，
                                    # 结果就是整块零件一起变暗，而不是接缝处出暗角。
        "subdiv_passes":    5,      # 最多切几轮
        # 分材质权重：金属件给低权重。金框是一条又薄又窄的环，紧挨着比它高的内板，
        # AO 会"正确地"把整条压暗，结果和四角凸出去的铆钉差出一个色。
        # 凹槽、井壁这些该暗的地方不受影响。
        "per_material": {
            "board_gold":      0.30,
            "board_gold_dark": 0.40,
            "board_accent":    0.60,
        },
        # 棱高光：平面相对棱压暗多少（0 = 关掉）。分材质给，金属件给大一点。
        # 顶点色只能压暗不能提亮，所以金的基础色是按"棱上不压暗"来定的。
        "edge_gain": {
            "board_gold":      0.38,
            "board_gold_dark": 0.25,
        },
        "edge_sharp":       6.0,    # 凸度到亮度的映射斜率，越大亮边越窄
    },

    # ---------------- 尖刺板 ----------------
    # 内板做成「井」字：外圈 Plate + 十字隔条 PlateCross，中间空出四个方槽。
    # 槽壁贴暗色内衬 Liner，槽底是砖体 Base 的顶面。
    "spikes": {
        "base_depth":       0.300,  # 砖体往地下的厚度。刺收回去要能整根藏进去
        "plate_inset":      0.000,  # 内板外沿从 gold_inner 再往里缩多少。
                                    # 0 = 内板直接顶到金框内沿，两者相接
        "plate_thick":      0.018,  # 内板这一层的厚度。板底 = plate_top - plate_thick
        "hole_count":       3,      # 每边几个洞（3 = 3×3 共九个）
        "plate_rim":        0.080,  # 内板靠四边那圈的宽度。
                                    # 按约定等于隔条全宽（= cross_half × 2），
                                    # 洞口宽度由它和 hole_count 反算出来
        "cross_half":       0.040,  # 隔条的半宽
        "hole_bottom":     -0.220,  # 方竖井的井底高度。**可以沉到地面以下** ——
                                    # traps.json 里 spikes 标了 cuts_floor，
                                    # 放下去的时候游戏会把那一格的地板让开
                                    # （scripts/main.gd 的 _pit_cells），
                                    # 所以井深不再被 plate_top 卡住了
        "cap_aspect":       0.80,  # 锥尖的**高宽比**（高 ÷ 宽）。
                                    # **别调高**：尖锥在井口露出的横截面极细，
                                    # 而刺的颜色是用来标等级的，看不见等于功能失效。
                                    # 实测静止时能看到的青色像素（spike_fill 一起调）：
                                    #   宽0.60 锥4.00 -> 0 个（完全看不见）
                                    #   宽0.42 锥1.30 -> 74 个
                                    #   宽0.48 锥0.90 -> 145 个
                                    #   宽0.60 锥0.45 -> 501 个 <- 参考图就是这种扁宽锥
                                    # 想要"长而尖"靠 spike_len（刺杆），不是靠这个
        "spike_fill":       0.60,   # 刺的宽度 ÷ 井口宽度。留出的缝正好露出井壁
        "spike_len":        0.450,  # 刺的**总长**（锥尖 + 刺杆）。
                                    # 决定扎出来能有多长，也就是井要多深才装得下
        "tip_below_plate":  0.002,  # 静止时刺尖比板面低多少。保证「不突出」
    },

    # ---------------- 弹簧板 ----------------
    # 弹出侧（-Y）有一条结构：深槽 Channel + 发光条 Glow + 两端螺栓 ChBolt。
    # 板子 Plate 绕这条结构的外沿翻起，箭头 Arrow 平嵌在板面里。
    "spring": {
        "channel_from_edge": 0.075, # 凹槽中心离内区边缘多远
        "channel_w":        0.620,  # 凹槽宽度（x 向）
        "channel_d":        0.120,  # 凹槽进深（y 向）
        # 铰链那一侧本来就没有板子盖着，天然就比板面低一截 —— 那里已经是凹槽了，
        # 不需要再堆一个块。Channel 只是铺在槽底的一层暗色，Glow 叠在它上面。
        # 老版本把 Channel 做成了从地面到板面的实心盒子，结果把 Glow 整个包在里面，
        # 发光条完全看不见。
        "glow_round":       True,   # 发光条做成圆轴。False 就退回方条
        "glow_radius_fill": 1.40,   # 圆轴直径 ÷ 凹槽深度。1.0 = 顶面和板面齐平，
                                    # 大于 1 会微微凸出凹槽，圆的形状才读得出来
                                    # （齐平的话只露出上半个弧，看着还是一条细线）
        "glow_w":           0.540,  # 发光条尺寸
        "glow_d":           0.078,  # 方条模式下的进深
        "glow_h":           0.010,  # 方条模式下的厚度
        "hinge_offset":     0.058,  # 铰链在凹槽中心外侧多远。板子绕这条线翻起
        "plate_w":          0.780,  # 板宽。要基本铺满内区（内区宽 gold_inner×2 = 0.800），
                                    # 留太多会从两侧露出底板的深色，看着像一圈黑边
        "plate_margin":     0.012,  # 板前沿离内区边缘留多少
        "plate_thick":      0.018,  # 和尖刺板的内板同厚
        "edge_outer":       0.390,  # 板边金线（方环）的外沿，要跟着 plate_w 走
        "edge_inner":       0.368,  # 和内沿
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
    # 金要够光滑反射才锐，金属感主要来自这里 + 环境的反射天空
    b.inputs["Roughness"].default_value = 0.15 if name == "board_gold" else (
        0.48 if name == "board_accent" else 0.82)
    if "Metallic" in b.inputs:
        # 环境已经挂了只给反射用的天空，金属件有东西可反射了，
        # 金属度可以给回高值 —— 之前压到 0.3 是因为没有反射，高金属度会渲成暗褐色。
        b.inputs["Metallic"].default_value = 0.25 if name.startswith("board_gold") else 0.0
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


def slab_with_holes(name, xs, ys, hole_cells, z0, z1, material, parent, bevel=0.008):
    """一整块带方洞的板，做成**单个网格**。

    xs / ys 是分带的边界坐标（n+1 个值分成 n 条带），hole_cells 里是要挖空的
    格子下标 (i, j)。

    为什么非要合成一个网格：拿几个盒子拼的话，每个盒子都会被倒角修出一圈棱，
    板面上就会看到一条条分界线。合成单个网格以后，内部那些边两侧的面是共面的
    （夹角 0），按角度限制的倒角会自动跳过它们，只倒真正的轮廓边。
    """
    nxs, nys = len(xs), len(ys)

    def vid(i, j, top):
        return (0 if top else nxs * nys) + i * nys + j

    verts = []
    for top in (True, False):
        z = z1 if top else z0
        for i in range(nxs):
            for j in range(nys):
                verts.append((xs[i], ys[j], z))

    faces = []
    holes = set(hole_cells)
    for i in range(nxs - 1):
        for j in range(nys - 1):
            if (i, j) in holes:
                continue
            faces.append((vid(i, j, True), vid(i + 1, j, True),
                          vid(i + 1, j + 1, True), vid(i, j + 1, True)))
            faces.append((vid(i, j + 1, False), vid(i + 1, j + 1, False),
                          vid(i + 1, j, False), vid(i, j, False)))

    # 外圈侧壁：沿外边界**逆时针**走一圈，法线朝外
    ring = ([(i, 0) for i in range(nxs - 1)] +
            [(nxs - 1, j) for j in range(nys - 1)] +
            [(i, nys - 1) for i in range(nxs - 1, 0, -1)] +
            [(0, j) for j in range(nys - 1, 0, -1)])
    for k in range(len(ring)):
        a, b = ring[k], ring[(k + 1) % len(ring)]
        faces.append((vid(a[0], a[1], False), vid(b[0], b[1], False),
                      vid(b[0], b[1], True), vid(a[0], a[1], True)))

    # 洞壁：沿洞边界**顺时针**走，法线才朝洞里
    for (i, j) in hole_cells:
        loop = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]
        for k in range(4):
            a, b = loop[k], loop[(k + 1) % 4]
            faces.append((vid(a[0], a[1], False), vid(b[0], b[1], False),
                          vid(b[0], b[1], True), vid(a[0], a[1], True)))
    return add(name, verts, faces, material, parent, bevel)


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


def bolts(name, parent, outer, size, cut, body_h, cap_h, cap_ratio, material, bevel=0.005,
          z0=0.0):
    """四角的方形铆钉 Bolt + 顶上一颗八角钉帽 BoltT。

    钉帽居中放在正方形的中心（不是放在格子角上），半径 size*cap_ratio。
    取 0.25 时直径约等于边长的一半 —— 中心到斜角的距离是 0.471*size，
    所以这个半径怎么都不会越过朝内的那个斜角。
    """
    c = outer - size * 0.5          # 正方形的中心到原点的距离
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (1, -1), (-1, -1))):
        prism("%s%d" % (name, i), bracket_pts(outer, size, cut, sx, sy),
              z0, z0 + body_h, material, parent, bevel=bevel)
        cyl("%sT%d" % (name, i), (sx * c, sy * c, z0 + body_h + cap_h * 0.5),
            size * cap_ratio, cap_h, material, parent,
            sides=8, rot_z=math.radians(22.5))


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

      Gold      金框，外沿直接顶到格子边（没有石缘，板子就坐在地面上），
                内沿和内板直接相接
      GoldLine  二级起金框内侧的暗金细线
      Bolt      四角的**方形**铆钉，外角贴着格子角，朝内的角切斜角
                （BoltT 是它顶上的收口）
    """
    # 金框从地面一直做到内板之上 —— 它要把整个叠层（底座 + 内板）都包住
    gold_h = fp("plate_top") + tier_val(fp("gold_above_plate"), fp("gold_above_step"))
    ring("Gold", frame, fp("gold_outer"), fp("gold_inner"), 0.0, gold_h, "board_gold")
    if _tier >= 2:
        ring("GoldLine", frame, fp("gold_inner") + fp("goldline_width"), fp("gold_inner"),
             0.0, gold_h + 0.010, "board_gold_dark")
    # 铆钉坐在金框**顶面**上。以前金框矮、铆钉从地面起还能露出来；
    # 金框加高以后再从地面起就整颗埋进去了。
    bolts("Bolt", frame, fp("gold_outer"),
          tier_val(fp("bolt_size"), fp("bolt_size_step")), fp("bolt_cut"),
          fp("bolt_body_h"), fp("bolt_cap_h"), fp("bolt_cap_ratio"), "board_gold",
          bevel=fp("bolt_bevel"), z0=gold_h)


def corner_leaves(parent, a0, a1, r, length, count, axis="z", phase=math.pi * 0.25):
    """四角（或八向）的叶片点缀，数量随等级增加。"""
    for i in range(count):
        a = phase + 2 * math.pi * i / count
        leaf("Leaf%d" % i, (math.cos(a) * r, math.sin(a) * r), length, length * 0.40,
             a0, a1, "board_gold", parent, angle=a + math.pi * 0.5, axis=axis)


# ----------------------------------------------------------------- 三种面板

def build_spring(root):
    """弹簧板。部件：

      固定（Frame）  Gold / Bolt  外框
                     Bed      板下面的底板，板翻起来以后露出来的就是它
                     Channel  弹出侧的凹槽（暗色，陷下去的）
                     Glow     凹槽里的发光条（等级色）
      活动（Mover）  Plate      板本体，绕凹槽外沿翻起
                     PlateEdge  板边一圈金线
                     Arrow      平嵌在板面里的箭头（等级色）
                     Leaf       板面上的叶片

    静止时 Plate 上表面和内板齐平，Arrow 只比板面高 0.005，所以是「平嵌」。
    """
    P = PARAMS["spring"]
    frame = joint("Frame", (0, 0, 0), root)
    floor_frame(frame)

    top = fp("plate_top")
    inner = fp("gold_inner")

    # 板下面的底板：板翻起来以后露出来的就是它。少了它板子是浮在空中的。
    box("Bed", (0, 0, (top - P["plate_thick"]) * 0.5),
        (inner * 2, inner * 2, top - P["plate_thick"]), "board_base", frame)

    # 弹出侧（-Y）的凹槽 + 发光条。设计图里这条是弹簧板最好认的特征，
    # 说明这一侧是铰链、往对面弹。注意它是**凹**进去的：从地面做到板面高度、
    # 用暗色材质，所以是一条沟；做成凸起的条就成了横在板上的梁。
    ch_y = -inner + P["channel_from_edge"]
    bed_top = top - P["plate_thick"]          # 槽底 = 底板上表面
    if P["glow_round"]:
        # 圆轴：直接躺在凹槽里，本身就是可见的那个件 —— 不再在它下面垫一根暗色条。
        # 原来是"暗色方条 + 上面盖一条蓝"，深色轴压在蓝块上不好看。
        r = P["plate_thick"] * 0.5 * P["glow_radius_fill"]
        cyl("Glow", (0, ch_y, bed_top + r), r, P["channel_w"], "board_accent", frame,
            axis="x", sides=14)
    else:
        box("Channel", (0, ch_y, bed_top + 0.003),
            (P["channel_w"], P["channel_d"], 0.006), "board_recess", frame)
        box("Glow", (0, ch_y, bed_top + 0.006 + P["glow_h"] * 0.5),
            (P["glow_w"], P["glow_d"], P["glow_h"]), "board_accent", frame)
    # 两端不再单独放螺栓：那两颗以前是八角柱，和新的方形角铆钉撞在一起，
    # 而且位置本来就和角铆钉重叠 —— 角铆钉已经起到那个作用了。

    # 板本体：铰链在凹槽外沿，静止时上表面和内板齐平
    hinge_y = ch_y + P["hinge_offset"]
    mover = joint("Mover", (0, hinge_y, 0.0), root)
    depth = inner - P["plate_margin"] - hinge_y
    cy = depth * 0.5
    box("Plate", (0, cy, top - P["plate_thick"] * 0.5), (P["plate_w"], depth, P["plate_thick"]),
        "board_plate", mover)
    ring("PlateEdge", mover, P["edge_outer"], P["edge_inner"],
         top - P["plate_thick"], top + 0.002,
         "board_gold" if _tier >= 2 else "board_gold_dark", center=(0, cy))

    prism("Arrow", place(arrow_pts(P["arrow_len"], P["arrow_shaft_w"],
                                   P["arrow_head_len"], P["arrow_head_w"]), (0, cy)),
          top - P["arrow_sink"], top + 0.005, "board_accent", mover, bevel=0.004)
    # 板面不放叶片装饰：留干净的一块，只有箭头
    return root


def build_spikes(root):
    """尖刺板。部件：

      固定（Frame）  Gold / Groove / Bolt  外框
                     Plate       浅灰内板，**一整块**带四个方洞的板
                     Base        底座，开着**同样的四个洞**，把方竖井继续往下开
                     BaseFloor   井底，实心，封住下面并挡住刺的下半截
      活动（Mover）  Spike       锥尖（等级色）
                     SpikeShaft  长刺杆，从锥尖一直往下，静止时填满可见的那段井

    洞是**贯穿下去的方竖井**，刺是长的，平时整根待在井里，触发时向上扎出。
    三个等级井形完全一样，只有刺的颜色不同。
    静止姿态就是导出的姿态：刺尖比板面低 tip_below_plate，不突出。

    井深受引擎限制：游戏里 y=0 以下会被地板挡住，所以可见井深最多就是
    plate_top。想要更深的井，只能把 plate_top 抬高。
    """
    P = PARAMS["spikes"]
    frame = joint("Frame", (0, 0, 0), root)
    mover = joint("Mover", (0, 0, 0), root)
    floor_frame(frame)

    inner = fp("gold_inner") - P["plate_inset"]
    top = fp("plate_top")
    bottom = top - P["plate_thick"]   # 板底
    floor_z = P["hole_bottom"]        # 井底

    # 洞的排布：靠边一圈 rim，中间 N 个洞、N-1 条隔条。
    # 洞宽由总宽反算，这样改 hole_count 或 rim 都不用手算坐标。
    n = int(P["hole_count"])
    div = P["cross_half"]
    rim = P["plate_rim"]
    hole_w = (2.0 * inner - 2.0 * rim - (n - 1) * 2.0 * div) / n
    xs = [-inner, -inner + rim]
    for i in range(n):
        xs.append(xs[-1] + hole_w)
        if i < n - 1:
            xs.append(xs[-1] + 2.0 * div)
    xs.append(inner)
    # 洞落在奇数号条带上（0 号是 rim，之后 洞/隔条 交替）
    idx = [1 + 2 * i for i in range(n)]
    holes = [(i, j) for i in idx for j in idx]

    # 内板和底座用**同一个洞网格**，方竖井就这么一路开到井底。
    # 拿外圈 + 十字拼的话每块都会被倒角修出一圈棱，板面上会看到分界线，
    # 所以两层都用 slab_with_holes 做成单个网格。
    slab_with_holes("Plate", xs, xs, holes, bottom, top, "board_plate", frame)
    slab_with_holes("Base", xs, xs, holes, floor_z, bottom, "board_base", frame)
    # 井底：实心，封住下面，同时把刺的下半截挡住
    box("BaseFloor", (0, 0, floor_z - P["base_depth"] * 0.5),
        (inner * 2, inner * 2, P["base_depth"]), "board_base", frame)


    # 刺：锥尖 + 长刺杆。静止时锥尖齐板面，刺杆填满可见的那段井，
    # 剩下的部分伸到井底以下（被 BaseFloor 挡住）。
    spike_w = hole_w * P["spike_fill"]
    tip = top - P["tip_below_plate"]
    cap_h = spike_w * P["cap_aspect"]   # 高宽比直接决定尖不尖
    cone_base = tip - cap_h          # 锥尖底面 = 刺杆顶面
    shaft_len = P["spike_len"] - cap_h
    # 每个洞的中心 = 那条带的中点
    centers = [(xs[k] + xs[k + 1]) * 0.5 for k in idx]
    for i, (sx, sy) in enumerate([(a, b) for a in centers for b in centers]):
        box("SpikeShaft%d" % i, (sx, sy, cone_base - shaft_len * 0.5),
            (spike_w, spike_w, shaft_len), "board_accent", mover)
        pyramid("Spike%d" % i, (sx, sy, cone_base), spike_w, cap_h, "board_accent", mover)
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

def apply_modifiers():
    """烘 AO 之前先把倒角等修改器实体化 —— 顶点色是存在顶点上的，
    修改器没应用的话，倒角新生成的那圈顶点拿不到自己的 AO。"""
    for ob in list(bpy.data.objects):
        if ob.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = ob
        for m in list(ob.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except RuntimeError:
                ob.modifiers.remove(m)


def subdivide_for_ao(max_edge, passes):
    """烘 AO 之前细分：把过长的边切开，让平面内部也有顶点承载 AO。

    自适应切 —— 只切长过 max_edge 的边，小零件不会被无谓地炸开。
    """
    import bmesh
    before = after = 0
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        before += len(bm.faces)
        # 烘 AO 之前统一把法线摆正：法线朝里的话 Cycles 会以为射线打进实体，
        # 那一面就会烘成全遮挡（弹簧板的板面就是这么烘黑的）。
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        for _ in range(passes):
            long_edges = [e for e in bm.edges if e.calc_length() > max_edge]
            if not long_edges:
                break
            bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=True)
        after += len(bm.faces)
        bm.to_mesh(ob.data)
        bm.free()
    print("AO_SUBDIV 面数 %d -> %d" % (before, after))


def vertex_convexity(me):
    """每个顶点的凸度：邻点相对顶点法线越"靠下"越凸（棱、角），返回 0..1。

    conv = 平均( -normalize(邻点 - 本点) · 顶点法线 )
    平面上邻点都在切平面内 -> 约等于 0；凸棱上邻点都在法线下方 -> 明显为正。
    """
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    out = [0.0] * len(bm.verts)
    for v in bm.verts:
        if not v.link_edges:
            continue
        acc, n = 0.0, 0
        for e in v.link_edges:
            d = e.other_vert(v).co - v.co
            if d.length < 1e-9:
                continue
            acc += -(d.normalized().dot(v.normal))
            n += 1
        if n:
            out[v.index] = acc / n
    bm.free()
    return out


def _group_of(ob):
    n = ob
    while n is not None:
        if n.name in ("Frame", "Mover"):
            return n.name
        n = n.parent
    return "Frame"


def _bake_group(meshes, others, samples):
    """只让 meshes 参与烘焙，others 临时从渲染里摘掉（不参与遮挡）。"""
    if not meshes:
        return
    for ob in others:
        ob.hide_render = True
    bpy.ops.object.select_all(action="DESELECT")
    for ob in meshes:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.bake(type="AO")
    for ob in others:
        ob.hide_render = False


def bake_ao():
    """把 AO 烘进每个网格的顶点色。"""
    cfg = PARAMS["ao"]
    if cfg["strength"] <= 0.0:
        return
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AOWorld")
    scene.world.light_settings.distance = cfg["distance"]

    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(cfg["samples"])
    scene.render.bake.target = "VERTEX_COLORS"
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False

    subdivide_for_ao(cfg["subdiv_edge"], int(cfg["subdiv_passes"]))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for ob in meshes:
        me = ob.data
        if not me.color_attributes:
            # 必须用 FLOAT_COLOR（线性）。BYTE_COLOR 在 Blender 里是 sRGB，
            # 导出 glTF 时会再做一次 sRGB->线性，AO 相当于被平方了一遍
            # （实测写进去 0.407，导出成 0.141）。
            me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="CORNER")
        me.color_attributes.active_color_index = 0

    frame = [o for o in meshes if _group_of(o) == "Frame"]
    mover = [o for o in meshes if _group_of(o) == "Mover"]
    # 固定件互相遮挡；活动件只算自遮挡（静止时埋在槽里，别把槽的阴影烘进去）
    _bake_group(frame, mover, cfg["samples"])
    _bake_group(mover, frame, cfg["samples"])

    # 调强度 + 兜底，避免角落烘成纯黑；强度按材质加权；
    # 再叠一层"棱高光"：平面相对棱压暗，金属件才有明暗层次。
    floor = cfg["floor"]
    per = cfg.get("per_material", {})
    egain = cfg.get("edge_gain", {})
    sharp = float(cfg.get("edge_sharp", 6.0))
    for ob in meshes:
        me = ob.data
        col = me.color_attributes.active_color
        if col is None:
            continue
        mname = me.materials[0].name if me.materials else ""
        k = cfg["strength"] * float(per.get(mname, 1.0))
        g = float(egain.get(mname, 0.0))
        conv = vertex_convexity(me) if g > 0.0 else None
        for i, d in enumerate(col.data):
            v = 1.0 - (1.0 - d.color[0]) * k
            v = floor + (1.0 - floor) * v
            if conv is not None:
                t = min(max(conv[me.loops[i].vertex_index] * sharp, 0.0), 1.0)
                v *= 1.0 - g * (1.0 - t)
            d.color = (v, v, v, 1.0)
    print("AO_BAKED %d 个网格" % len(meshes))


def preview_vertex_color():
    """只给预览渲染用：把顶点色乘进 Base Color，这样预览图看到的和游戏里一致。
    必须在导出之后调 —— glTF 导出器碰到接了节点的 Base Color 会另作处理。"""
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        b = m.node_tree.nodes.get("Principled BSDF")
        if b is None:
            continue
        base = tuple(b.inputs["Base Color"].default_value)
        vc = m.node_tree.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "Col"
        mix = m.node_tree.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.inputs["Color1"].default_value = base
        m.node_tree.links.new(vc.outputs["Color"], mix.inputs["Color2"])
        m.node_tree.links.new(mix.outputs["Color"], b.inputs["Base Color"])


def export(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(path), export_format="GLB",
                              export_apply=True, export_yup=True, use_selection=True,
                              export_materials="EXPORT", export_animations=False,
                              export_skins=False,
                              # 材质没接 Color Attribute 节点，用 MATERIAL 模式就不会导出
                              # 顶点色了，必须显式给 ACTIVE
                              export_vertex_color="ACTIVE")
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


def build_one(variant, tier, out_path, render_dir, part_map_dir=None, ao=True):
    global _tier
    _tier = tier
    clear()
    root = joint("Root", (0, 0, 0))
    BUILDERS[variant](root)
    if ao:
        apply_modifiers()       # 顶点色存在顶点上，倒角得先实体化
        bake_ao()
    export(out_path)
    if ao:
        preview_vertex_color()  # 只影响预览渲染，导出已经做完了
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
    ao = "--no-ao" not in (sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    variants = [variant] if variant else VARIANTS
    tiers = [int(tier)] if tier else TIERS
    single = variant is not None and tier is not None and out.lower().endswith(".glb")

    for v in variants:
        if v not in BUILDERS:
            print("未知面板类型：%s（可选 %s）" % (v, "/".join(VARIANTS)))
            sys.exit(1)
        for t in tiers:
            path = out if single else os.path.join(out, "board_%s_%d.glb" % (v, t))
            build_one(v, t, path, render_dir, part_map_dir, ao)


if __name__ == "__main__":
    main()
