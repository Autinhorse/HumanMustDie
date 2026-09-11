"""
剑士 / 盾兵模型：参考 ref/swordman.png，全部用盒子搭，不做骨骼。
两种敌人共用同一套骨架，`--variant shieldman` 会在左臂上加一面盾并把左臂抬起来。

关键点是**每个部件的原点放在关节上**（颈、肩、髋、握把），这样导进 Godot 之后
直接给节点转角度就能做跑步和倒地动画，不需要骨骼和动画数据。

层级：
  Root
   ├ Torso          原点在髋部
   │   ├ Head       原点在颈部
   │   ├ ArmL       原点在左肩
   │   └ ArmR       原点在右肩
   │       └ Sword  原点在握把
   ├ LegL           原点在左髋
   └ LegR           原点在右髋

模型总高 1.0，**朝 +Y**（面罩在 +Y 面）。glTF 转 Y-up 后 Blender +Y -> -Z，
正好是 Godot 的前方，所以 Godot 里用 atan2(-dx, -dz) 转向就对。

用法：
  blender --background --python tools/blender/build_swordman.py -- \
      --out assets/models/swordman.glb --render renders/swordman.png
"""

import bpy
import math
import os
import sys
from mathutils import Vector

# ----------------------------------------------------------------- 比例（总高 1.0）

P = {
    "leg_h": 0.28, "leg_w": 0.13, "leg_d": 0.15, "leg_gap": 0.03,
    "boot_h": 0.07, "boot_over": 0.015,
    "torso_h": 0.38, "torso_w": 0.36, "torso_d": 0.23,
    "belt_h": 0.055,
    "head_h": 0.33, "head_w": 0.38, "head_d": 0.33, "head_top_shrink": 0.66,
    "head_straight": 0.70,   # 头盔下面这部分是直筒，上面才斜切
    "collar_h": 0.06,
    "visor_y": 0.40, "visor_h": 0.085, "visor_w": 0.62,
    "arm_w": 0.105, "arm_d": 0.135, "upper_arm": 0.22, "fore_arm": 0.12,
    "shoulder_drop": 0.03,
    "blade_len": 0.42, "blade_w": 0.075, "blade_d": 0.028, "tip_len": 0.10,
    "guard_w": 0.20, "guard_h": 0.035, "grip_len": 0.09,
    # 盾兵
    "shield_arm_lift": 52.0,   # 左臂前抬角度
    "shield_fwd": 0.17,        # 盾往前推出多少
    "shield_side": 0.03,       # 盾再往左手那侧挪一点
    "shield_rx": 0.180, "shield_rz": 0.265, "shield_thick": 0.05,
    "shield_rim": 0.030,       # 边框比盘面大多少
    "shield_bar": 0.055,       # 十字条宽度
}

COLORS = {
    "armor_primary": (0.106, 0.278, 0.671),   # 蓝 主色，Godot 里会按敌人类型换
    "armor_dark":    (0.098, 0.176, 0.392),   # 深蓝 腿/护手
    "cloth_red":     (0.686, 0.106, 0.125),   # 红 上臂
    "metal_gold":    (0.949, 0.733, 0.157),   # 金 腰带/头盔边/靴/护手
    "metal_blade":   (0.878, 0.894, 0.906),   # 剑刃
    "visor_black":   (0.035, 0.035, 0.043),
}


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
    b.inputs["Roughness"].default_value = 0.85
    if "Metallic" in b.inputs:
        b.inputs["Metallic"].default_value = 0.0
    for s in ("Specular IOR Level", "Specular"):
        if s in b.inputs:
            b.inputs[s].default_value = 0.2
    return m


def box(name, center, size, material, parent, top_scale=1.0, bevel=0.012,
        rotation=None):
    """在 parent 关节的**局部坐标系**里建一个盒子。
    直接用局部坐标建几何，不碰 matrix_parent_inverse —— 那个依赖世界矩阵，
    而新建的物体在依赖图更新前世界矩阵还是单位阵，会把部件甩飞。"""
    cx, cy, cz = center
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    tx, ty = hx * top_scale, hy * top_scale
    verts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - tx, cy - ty, cz + hz), (cx + tx, cy - ty, cz + hz),
        (cx + tx, cy + ty, cz + hz), (cx - tx, cy + ty, cz + hz),
    ]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
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
    if rotation:
        ob.rotation_euler = rotation
    return ob


def ellipse(name, center, rx, rz, thickness, material, parent, bevel=0.008):
    """椭圆盘：在 XZ 平面画 n 边形，沿 Y（角色前方）挤出。用来做盾牌。"""
    cx, cy, cz = center
    sides = 22
    hy = thickness / 2.0
    verts, faces = [], []
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((cx + math.cos(a) * rx, cy - hy, cz + math.sin(a) * rz))
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((cx + math.cos(a) * rx, cy + hy, cz + math.sin(a) * rz))
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, j + sides, i + sides))
    faces.append(tuple(range(sides - 1, -1, -1)))
    faces.append(tuple(range(sides, sides * 2)))
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


def joint(name, local_pos, parent=None, rotation=None):
    """关节 = 一个空物体，位置用**相对父节点**的局部坐标，旋转轴就在它身上"""
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.04
    e.location = local_pos
    if rotation:
        e.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(e)
    if parent:
        e.parent = parent
    return e


# ----------------------------------------------------------------- 建模

def build(variant="swordman"):
    clear()
    leg_top = P["leg_h"]
    torso_h = P["torso_h"]
    head_h = P["head_h"]

    root = joint("Root", (0, 0, 0))

    # --- 躯干：原点在髋部
    torso = joint("Torso", (0, 0, leg_top), root)
    box("TorsoBody", (0, 0, torso_h / 2), (P["torso_w"], P["torso_d"], torso_h),
        "armor_primary", torso, top_scale=1.04)
    box("Belt", (0, 0, P["belt_h"] / 2),
        (P["torso_w"] * 1.04, P["torso_d"] * 1.04, P["belt_h"]), "metal_gold", torso)
    # 胸口菱形：压扁的方板绕 Y 转 45 度
    box("Emblem", (0, 0, 0), (0.10, 0.02, 0.10), "metal_gold", torso, bevel=0.004,
        rotation=(0, math.radians(45), 0)).location = (0, P["torso_d"] / 2 + 0.004, torso_h * 0.60)

    # --- 头：原点在颈部
    head = joint("Head", (0, 0, torso_h), torso)
    box("Collar", (0, 0, P["collar_h"] / 2),
        (P["head_w"] * 0.86, P["head_d"] * 0.86, P["collar_h"]), "metal_gold", head)
    # 参考图的头盔是直筒，只有顶部斜切，不是整个收窄的灯罩
    straight_top = P["collar_h"] + (head_h - P["collar_h"]) * P["head_straight"]
    box("Helmet", (0, 0, (P["collar_h"] + straight_top) / 2),
        (P["head_w"], P["head_d"], straight_top - P["collar_h"]), "armor_primary", head)
    box("HelmetTop", (0, 0, (straight_top + head_h) / 2),
        (P["head_w"], P["head_d"], head_h - straight_top), "armor_primary", head,
        top_scale=P["head_top_shrink"])
    box("Visor", (0, P["head_d"] / 2 + 0.002, head_h * P["visor_y"]),
        (P["head_w"] * P["visor_w"], 0.03, P["visor_h"]), "visor_black", head, bevel=0.004)

    # --- 手臂：原点在肩
    shoulder_z = torso_h - P["shoulder_drop"]
    arm_x = P["torso_w"] * 1.04 / 2 + P["arm_w"] / 2 + 0.008
    for side, sx in (("L", -1.0), ("R", 1.0)):
        # 盾兵的左臂抬起来横在身前托盾，所以关节自带一个前抬角
        rot = None
        if variant == "shieldman" and side == "L":
            rot = (math.radians(P["shield_arm_lift"]), 0, 0)
        arm = joint("Arm%s" % side, (sx * arm_x, 0, shoulder_z), torso, rotation=rot)
        box("Upper%s" % side, (0, 0, -P["upper_arm"] / 2),
            (P["arm_w"], P["arm_d"], P["upper_arm"]), "cloth_red", arm)
        box("Fore%s" % side, (0, 0, -P["upper_arm"] - P["fore_arm"] / 2),
            (P["arm_w"] * 1.03, P["arm_d"] * 1.03, P["fore_arm"]), "armor_dark", arm)
        if side == "R":
            build_sword(arm, -P["upper_arm"] - P["fore_arm"])
        elif variant == "shieldman":
            build_shield(arm, -P["upper_arm"] - P["fore_arm"] * 0.5)

    # --- 腿：原点在髋
    leg_x = P["leg_w"] / 2 + P["leg_gap"] / 2
    for side, sx in (("L", -1.0), ("R", 1.0)):
        leg = joint("Leg%s" % side, (sx * leg_x, 0, leg_top), root)
        box("Shin%s" % side, (0, 0, -(P["leg_h"] - P["boot_h"]) / 2),
            (P["leg_w"], P["leg_d"], P["leg_h"] - P["boot_h"]), "armor_dark", leg)
        box("Boot%s" % side, (0, -0.012, -P["leg_h"] + P["boot_h"] / 2),
            (P["leg_w"] + P["boot_over"], P["leg_d"] + P["boot_over"] * 2.4, P["boot_h"]),
            "metal_gold", leg, top_scale=0.92)

    return root


def build_shield(arm, hand_z):
    """盾：椭圆板 + 一圈异色边 + 贯穿上下左右的十字。挂在左臂上，盘面朝角色前方 +Y。"""
    # 左臂抬起来了，这里把盾转回来让盘面竖直朝前
    shield = joint("Shield", (-P["shield_side"], P["shield_fwd"], hand_z),
                   arm, rotation=(math.radians(-P["shield_arm_lift"]), 0, 0))
    rx, rz = P["shield_rx"], P["shield_rz"]
    t = P["shield_thick"]
    # 边框：比盘面大一圈、往后错一点，露出来就是一圈边
    ellipse("ShieldRim", (0, 0, 0), rx + P["shield_rim"], rz + P["shield_rim"], t, "metal_gold", shield)
    ellipse("ShieldFace", (0, t * 0.45, 0), rx, rz, t, "armor_primary", shield)
    # 十字：横竖两条贯穿到边框
    bar = P["shield_bar"]
    # 十字刚好顶到边框内沿，别戳出去
    # 十字用金色：盾面是会按敌人换色的主色，暗色十字在深色敌人身上会糊掉
    box("ShieldBarV", (0, t * 0.75, 0), (bar, t * 0.7, (rz + P["shield_rim"] * 0.5) * 2.0),
        "metal_gold", shield, bevel=0.004)
    box("ShieldBarH", (0, t * 0.75, 0), ((rx + P["shield_rim"] * 0.5) * 2.0, t * 0.7, bar),
        "metal_gold", shield, bevel=0.004)
    return shield


def build_sword(arm, hand_z):
    """剑：原点在握把，挂在右臂下。死亡动画里把它从手上解绑扔出去。"""
    # 剑尖朝上握在手里，刀身沿局部 +Z。
    # 外倾角（绕 Y）必须小：等距相机下，往镜头方向倾的线会被压扁成近似水平，
    # 倾得多了不同朝向看起来就会"一会朝上一会朝下"。之前误设成 45 度就是这个毛病。
    # 握把改放到手臂外侧面上，这样只要很小的外倾角就能让刀身避开上臂。
    # 绕 X 负角 = 刀身往前倾（角色朝 +Y）；绕 Y 小角 = 往身体外侧让开上臂
    sword = joint("Sword", (0.050, 0.03, hand_z + 0.02), arm,
                  rotation=(math.radians(-30), math.radians(8), 0))
    box("Grip", (0, 0, -P["grip_len"] / 2), (0.036, 0.036, P["grip_len"]), "armor_dark", sword)
    box("Guard", (0, 0, 0), (P["guard_w"], 0.045, P["guard_h"]), "metal_gold", sword)
    box("Pommel", (0, 0, -P["grip_len"]), (0.05, 0.05, 0.035), "metal_gold", sword)
    box("Blade", (0, 0, P["blade_len"] / 2), (P["blade_w"], P["blade_d"], P["blade_len"]),
        "metal_blade", sword, bevel=0.006)
    box("Tip", (0, 0, P["blade_len"] + P["tip_len"] / 2),
        (P["blade_w"], P["blade_d"], P["tip_len"]), "metal_blade", sword,
        top_scale=0.08, bevel=0.004)
    return sword


# ----------------------------------------------------------------- 导出与预览

def export_glb(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=os.path.abspath(path),
        export_format="GLB",
        export_apply=True,          # 应用倒角修改器
        export_yup=True,            # Godot 是 Y-up
        use_selection=True,
        export_materials="EXPORT",
        export_animations=False,
        export_skins=False,
    )
    print("EXPORTED %s" % os.path.abspath(path))


def render_preview(path):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.80, 0.84, 0.84, 1)
    bg.inputs["Strength"].default_value = 0.7

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 1.55
    cam = bpy.data.objects.new("Cam", cam_data)
    # 角色朝 +Y，所以相机放到 +Y 一侧才拍到正面
    cam.location = (-1.15, 1.55, 1.05)
    d = (Vector((0, 0, 0.52)) - Vector(cam.location)).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    sun = bpy.data.lights.new("Sun", type="SUN")
    sun.energy = 2.6
    sun.angle = math.radians(12)
    s = bpy.data.objects.new("Sun", sun)
    s.rotation_euler = (math.radians(52), 0, math.radians(-35))
    scene.collection.objects.link(s)

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 700
    scene.render.resolution_y = 900
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
    out = "assets/models/swordman.glb"
    preview = ""
    variant = "swordman"
    i = 0
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--render" and i + 1 < len(argv):
            preview = argv[i + 1]
            i += 2
        elif argv[i] == "--variant" and i + 1 < len(argv):
            variant = argv[i + 1]
            i += 2
        else:
            i += 1
    build(variant)
    if preview:
        render_preview(preview)
    export_glb(out)


if __name__ == "__main__":
    main()
