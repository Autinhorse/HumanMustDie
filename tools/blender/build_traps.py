"""
机关模型：五种原型机关，全部程序化生成，不做骨骼。

和角色一样，**活动部件单独命名**，Godot 里直接给节点转角度/挪位置就能做触发动作：

  地刺   Spikes  上下伸缩
  黏胶   Surface 轻微起伏
  弹射板 Plate   绕铰链翻起
  推墙   Ram     沿朝向推出
  锯墙   Blade   持续旋转

约定：
- 模型按 **1×1 格**建（x/z 在 ±0.5 内），Godot 里按 cell_size 缩放。
- 朝 **+Y**（和角色一致）。glTF 转 Y-up 后就是 Godot 的前方 -Z。
- 墙面机关的原点在墙面上，本体往 +Y（朝向）方向伸出。
- 材质 `trap_primary` 会在 Godot 里按 traps.json 的 color 换色，其余固定。

用法：
  blender --background --python tools/blender/build_traps.py -- \
      --variant spikes --out assets/models/trap_spikes.glb
  不传 --variant 就一次导出全部五种（--out 当成目录用）。
"""

import bpy
import math
import os
import sys

COLORS = {
    "trap_primary": (0.70, 0.72, 0.75),   # 会被 Godot 换成机关自己的颜色
    "trap_metal":   (0.28, 0.30, 0.34),
    "trap_dark":    (0.16, 0.17, 0.20),
    "trap_wood":    (0.42, 0.30, 0.19),
    "trap_gold":    (0.85, 0.66, 0.22),
    "trap_blade":   (0.86, 0.88, 0.90),
    "trap_goo":     (0.45, 0.62, 0.30),
}

VARIANTS = ["spikes", "tar", "launcher", "push_wall", "saw"]


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
    c = COLORS[name]
    b.inputs["Base Color"].default_value = (c[0], c[1], c[2], 1.0)
    b.inputs["Roughness"].default_value = 0.55 if name in ("trap_blade", "trap_gold") else 0.85
    if "Metallic" in b.inputs:
        b.inputs["Metallic"].default_value = 0.6 if name in ("trap_blade", "trap_gold", "trap_metal") else 0.0
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


def add(name, verts, faces, material, parent, bevel=0.01):
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


def box(name, center, size, material, parent, top_scale=1.0, bevel=0.01, rotation=None):
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    tx, ty = hx * top_scale, hy * top_scale
    v = [(cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
         (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
         (cx - tx, cy - ty, cz + hz), (cx + tx, cy - ty, cz + hz),
         (cx + tx, cy + ty, cz + hz), (cx - tx, cy + ty, cz + hz)]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    ob = add(name, v, f, material, parent, bevel)
    if rotation:
        ob.rotation_euler = rotation
    return ob


def cyl(name, center, radius, height, material, parent, axis="z", sides=16, bevel=0.006):
    """圆柱。axis 决定轴向，用来做锯片（绕 X）和柱子（绕 Z）。"""
    cx, cy, cz = center
    v, f = [], []
    h = height / 2.0
    for sign in (-1, 1):
        for i in range(sides):
            a = 2 * math.pi * i / sides
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


def gear(name, center, radius, thickness, material, parent, teeth=10,
         tooth=0.12, axis="z", sides=18):
    """齿轮：一个盘 + 一圈方齿。机械感的主要来源，配合 cyl 做轴。"""
    g = joint(name + "Grp", center, parent,
              rotation=(math.radians(90), 0, 0) if axis == "y" else None)
    cyl(name, (0, 0, 0), radius, thickness, material, g, sides=sides)
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        box("%sT%d" % (name, i), (math.cos(a) * radius, math.sin(a) * radius, 0),
            (tooth, tooth, thickness * 0.85), material, g, bevel=0.004, rotation=(0, 0, a))
    return g


def coil(name, center, radius, height, material, parent, turns=5):
    """弹簧：用一叠环片近似，远看就是弹簧，比真螺旋便宜得多。"""
    g = joint(name + "Grp", center, parent)
    for i in range(turns):
        t = i / max(turns - 1.0, 1.0)
        cyl("%sR%d" % (name, i), (0, 0, (t - 0.5) * height),
            radius * (1.0 - 0.06 * abs(t - 0.5) * 2), height / turns * 0.55,
            material, g, sides=12, bevel=0.004)
    return g


def pyramid(name, center, base, height, material, parent, bevel=0.005):
    cx, cy, cz = center
    h = base / 2.0
    v = [(cx - h, cy - h, cz), (cx + h, cy - h, cz), (cx + h, cy + h, cz), (cx - h, cy + h, cz),
         (cx, cy, cz + height)]
    f = [(0, 1, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)]
    return add(name, v, f, material, parent, bevel)


# ----------------------------------------------------------------- 五种机关

def build_spikes(root):
    """地刺：带齿的框 + 侧面卷扬齿轮。静止时刺尖露在槽口外，一眼看得出是刺阵。"""
    box("Base", (0, 0, 0.03), (0.90, 0.90, 0.07), "trap_metal", root)
    # 槽板：四边加高框，中间凹下去，刺从凹槽里钻出来
    for sx, sy, w, h in ((0, 0.45, 0.98, 0.10), (0, -0.45, 0.98, 0.10),
                         (0.45, 0, 0.10, 0.82), (-0.45, 0, 0.10, 0.82)):
        box("Frame%d_%d" % (int(sx * 100), int(sy * 100)), (sx, sy, 0.10), (w, h, 0.14),
            "trap_primary", root)
    for cx in (-0.43, 0.43):
        for cy in (-0.43, 0.43):
            cyl("Bolt%d_%d" % (int(cx * 100), int(cy * 100)), (cx, cy, 0.18), 0.045, 0.05,
                "trap_gold", root, sides=8)
    # 侧面的卷扬机构：齿轮 + 轴，说明刺是被摇上来的
    gear("Winch", (0.50, -0.18, 0.12), 0.13, 0.05, "trap_gold", root, teeth=9, tooth=0.07, axis="y")
    cyl("WinchAxle", (0.30, -0.18, 0.12), 0.03, 0.44, "trap_metal", root, axis="x", sides=8)

    spikes = joint("Spikes", (0, 0, 0), root)
    box("SpikeBed", (0, 0, 0.04), (0.74, 0.74, 0.06), "trap_metal", spikes)
    for gx in (-0.26, 0, 0.26):
        for gy in (-0.26, 0, 0.26):
            pyramid("Spike%d_%d" % (int(gx * 100), int(gy * 100)), (gx, gy, 0.07),
                    0.17, 0.42, "trap_blade", spikes)
    return root


def build_tar(root):
    """黏胶：带格栅的池子 + 侧面供料罐和管子，不然只是一摊绿色。"""
    box("Basin", (0, 0, 0.02), (0.96, 0.96, 0.04), "trap_dark", root)
    for sx, sy, w, h in ((0, 0.46, 0.98, 0.08), (0, -0.46, 0.98, 0.08),
                         (0.46, 0, 0.08, 0.84), (-0.46, 0, 0.08, 0.84)):
        box("Rim%d_%d" % (int(sx * 100), int(sy * 100)), (sx, sy, 0.06), (w, h, 0.09),
            "trap_metal", root)
    # 池底格栅：胶从缝里渗上来
    for i in range(4):
        y = -0.30 + i * 0.20
        box("Grate%d" % i, (0, y, 0.045), (0.80, 0.05, 0.04), "trap_metal", root, bevel=0.004)
    # 供料罐 + 管子
    cyl("Tank", (-0.40, -0.40, 0.20), 0.13, 0.34, "trap_metal", root, sides=14)
    cyl("TankCap", (-0.40, -0.40, 0.39), 0.10, 0.06, "trap_gold", root, sides=14)
    cyl("Pipe", (-0.18, -0.40, 0.10), 0.045, 0.46, "trap_metal", root, axis="x", sides=10)
    cyl("Valve", (-0.40, -0.40, 0.10), 0.07, 0.06, "trap_gold", root, sides=10)

    surf = joint("Surface", (0, 0, 0), root)
    cyl("Goo", (0, 0, 0.06), 0.43, 0.07, "trap_primary", surf, sides=22)
    for x, y, r in ((0.16, 0.10, 0.10), (-0.14, -0.06, 0.07), (0.02, -0.22, 0.05),
                    (-0.22, 0.20, 0.06)):
        cyl("Bubble%d" % int(x * 100 + y * 10), (x, y, 0.09), r, 0.05, "trap_goo", surf, sides=12)
    return root


def build_launcher(root):
    """弹射板：铰链在后，两根扭簧在前顶起板子，板面加肋条。"""
    box("Base", (0, 0, 0.03), (0.94, 0.94, 0.06), "trap_metal", root)
    # 铰链在 -Y 那侧（角色朝 +Y，所以板子往前掀）
    for sx in (-0.40, 0.40):
        box("Ear%d" % int(sx * 100), (sx, -0.40, 0.13), (0.12, 0.16, 0.20), "trap_dark", root)
    cyl("Hinge", (0, -0.40, 0.15), 0.055, 0.94, "trap_gold", root, axis="x", sides=12)
    gear("HingeGear", (0.46, -0.40, 0.15), 0.14, 0.05, "trap_gold", root,
         teeth=10, tooth=0.07, axis="y")
    # 前端两根弹簧，把板子顶起来的那个力
    for sx in (-0.28, 0.28):
        coil("Spring%d" % int(sx * 100), (sx, 0.26, 0.14), 0.085, 0.17, "trap_gold", root)
    # 限位挡块
    for sx in (-0.44, 0.44):
        box("Stop%d" % int(sx * 100), (sx, 0.40, 0.10), (0.10, 0.14, 0.12), "trap_dark", root)

    plate = joint("Plate", (0, -0.40, 0.15), root)
    box("PlateBody", (0, 0.40, 0.02), (0.84, 0.86, 0.08), "trap_primary", plate)
    for i in range(3):
        box("PlateRib%d" % i, (-0.28 + i * 0.28, 0.40, -0.04), (0.10, 0.80, 0.06),
            "trap_metal", plate, bevel=0.005)
    box("PlateLip", (0, 0.80, 0.09), (0.84, 0.08, 0.14), "trap_gold", plate)
    return root


def build_push_wall(root):
    """推墙：机箱占满墙高，侧面大齿轮 + 活塞杆 + 配重，撞头带缓冲垫。"""
    # 机箱：贴在墙上，尽量占满墙高，远看才有体积
    box("Frame", (0, 0.09, 0.40), (0.92, 0.18, 0.78), "trap_dark", root)
    box("FrameCap", (0, 0.11, 0.81), (0.96, 0.22, 0.08), "trap_metal", root)
    box("FrameFoot", (0, 0.11, 0.03), (0.96, 0.22, 0.07), "trap_metal", root)
    # 两侧导轨
    for sx in (-0.40, 0.40):
        box("Rail%d" % int(sx * 100), (sx, 0.16, 0.40), (0.11, 0.30, 0.60), "trap_metal", root)
        for sz in (0.16, 0.64):
            cyl("Bolt%d_%d" % (int(sx * 100), int(sz * 100)), (sx, 0.04, sz), 0.05, 0.12,
                "trap_gold", root, axis="y", sides=8)
    # 侧面的驱动齿轮和配重：一眼看出是机械推出来的
    gear("Drive", (0.50, 0.14, 0.56), 0.20, 0.06, "trap_gold", root, teeth=12, tooth=0.09, axis="y")
    gear("Idler", (0.50, 0.14, 0.22), 0.11, 0.06, "trap_metal", root, teeth=8, tooth=0.07, axis="y")
    box("Weight", (-0.50, 0.14, 0.30), (0.14, 0.20, 0.26), "trap_metal", root)

    ram = joint("Ram", (0, 0, 0), root)
    # 静止时撞头贴着机箱（机箱正面在 y=0.18），杆藏在撞头里；
    # 推出去以后杆才从机箱和撞头之间露出来，那一截就是"推"的动作
    cyl("RamRod", (0, 0.16, 0.40), 0.09, 0.34, "trap_metal", ram, axis="y", sides=12)
    box("RamHead", (0, 0.31, 0.40), (0.74, 0.26, 0.66), "trap_primary", ram)
    # 缓冲条只做上下两条，中间留出撞头本体的识别色（铺满整面会把颜色全挡住）
    for sz in (0.14, 0.66):
        box("RamPad%d" % int(sz * 100), (0, 0.46, sz), (0.78, 0.06, 0.16), "trap_dark", ram)
    for sz in (0.16, 0.64):
        box("RamBand%d" % int(sz * 100), (0, 0.31, sz), (0.78, 0.28, 0.07), "trap_metal", ram,
            bevel=0.005)
    return root


def build_saw(root):
    """锯墙：摇臂把大锯片甩出墙外，臂根一对齿轮传动，锯片整片露在外面。"""
    box("Mount", (0, 0.08, 0.42), (0.56, 0.16, 0.72), "trap_primary", root)
    box("MountCap", (0, 0.10, 0.80), (0.62, 0.20, 0.08), "trap_metal", root)
    for sz in (0.18, 0.66):
        cyl("MountBolt%d" % int(sz * 100), (0, 0.02, sz), 0.05, 0.10, "trap_gold", root,
            axis="y", sides=8)
    # 传动：电机齿轮 -> 臂根齿轮
    gear("Motor", (0, 0.20, 0.22), 0.15, 0.07, "trap_metal", root, teeth=10, tooth=0.08, axis="y")
    gear("Pivot", (0, 0.22, 0.56), 0.13, 0.07, "trap_gold", root, teeth=9, tooth=0.07, axis="y")
    # 摇臂：斜着把锯片送到墙外，锯片就不会埋在机箱里
    box("Arm", (0, 0.40, 0.62), (0.15, 0.50, 0.15), "trap_metal", root,
        rotation=(math.radians(-18), 0, 0))
    cyl("Axle", (0, 0.62, 0.56), 0.055, 0.18, "trap_gold", root, axis="y", sides=10)

    blade = joint("Blade", (0, 0.62, 0.56), root, rotation=(math.radians(90), 0, 0))
    cyl("BladeDisc", (0, 0, 0), 0.42, 0.05, "trap_blade", blade, sides=24)
    cyl("BladeHub", (0, 0, 0), 0.13, 0.10, "trap_primary", blade, sides=14)
    for i in range(3):        # 减重孔，转起来看得出在转
        a = 2 * math.pi * i / 3
        cyl("BladeHole%d" % i, (math.cos(a) * 0.25, math.sin(a) * 0.25, 0), 0.075, 0.07,
            "trap_metal", blade, sides=10)
    for i in range(12):
        a = 2 * math.pi * i / 12
        box("Tooth%d" % i, (math.cos(a) * 0.45, math.sin(a) * 0.45, 0), (0.13, 0.13, 0.05),
            "trap_blade", blade, bevel=0.004, rotation=(0, 0, a))
    return root


BUILDERS = {
    "spikes": build_spikes, "tar": build_tar, "launcher": build_launcher,
    "push_wall": build_push_wall, "saw": build_saw,
}


# ----------------------------------------------------------------- 导出与预览

def export(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(path), export_format="GLB",
                              export_apply=True, export_yup=True, use_selection=True,
                              export_materials="EXPORT", export_animations=False, export_skins=False)
    print("EXPORTED %s" % os.path.abspath(path))


def render_preview(path, ortho=1.9, target=(0, 0, 0.3)):
    from mathutils import Vector
    scene = bpy.context.scene
    w = bpy.data.worlds.new("W")
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.78, 0.82, 0.83, 1)
    bg.inputs["Strength"].default_value = 0.75

    cd = bpy.data.cameras.new("Cam")
    cd.type = "ORTHO"
    cd.ortho_scale = ortho
    cam = bpy.data.objects.new("Cam", cd)
    cam.location = (-1.5, 1.9, 1.5)
    d = (Vector(target) - Vector(cam.location)).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    sl = bpy.data.lights.new("Sun", type="SUN")
    sl.energy = 2.6
    sl.angle = math.radians(12)
    s = bpy.data.objects.new("Sun", sl)
    s.rotation_euler = (math.radians(52), 0, math.radians(-140))
    scene.collection.objects.link(s)

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 520
    scene.render.resolution_y = 520
    scene.render.image_settings.file_format = "PNG"
    if hasattr(scene, "view_settings"):
        scene.view_settings.view_transform = "Standard"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    print("RENDERED %s" % os.path.abspath(path))


def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    variant = ""
    out = "assets/models"
    preview_dir = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--variant" and i + 1 < len(argv):
            variant = argv[i + 1]; i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out = argv[i + 1]; i += 2
        elif argv[i] == "--render-dir" and i + 1 < len(argv):
            preview_dir = argv[i + 1]; i += 2
        else:
            i += 1

    targets = [variant] if variant else VARIANTS
    for v in targets:
        clear()
        root = joint("Root", (0, 0, 0))
        BUILDERS[v](root)
        if preview_dir:
            render_preview(os.path.join(preview_dir, "trap_%s.png" % v))
        path = out if variant and out.endswith(".glb") else os.path.join(out, "trap_%s.glb" % v)
        export(path)


if __name__ == "__main__":
    main()
