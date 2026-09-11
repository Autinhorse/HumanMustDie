"""
读游戏自己的关卡数据，在 Blender 里搭出"空中悬浮岛"风格的场景并渲染。
参考风格：Isle of Arrows —— 奶白顶面 + 灰岩侧面 + 下挂深色岩体 + 青灰雾气 + 正交高角 + 柔和阴影。

用法（无头）：
  blender --background --python tools/blender/build_island.py -- \
      --project . --level corridor_01 --out renders/island.png

关卡、配色、岩体参数都从 data/*.json 读，和游戏共用同一份数据；
只有渲染本身的参数（太阳强度、曝光、雾距离）在本文件的 STYLE 里。
"""

import bpy
import bmesh  # noqa: F401  (保留：后续做倒角/融合时会用)
import json
import math
import os
import random
import sys
from mathutils import Vector

# ----------------------------------------------------------------- 风格参数

STYLE = {
    # 配色（线性空间之前的 sRGB 值，脚本里会转）
    "floor_top":   "#EDE8DB",
    "floor_top_b": "#DCD5C4",
    "floor_top_c": "#C6BFAF",
    "floor_side":  "#A79F92",
    "bridge":      "#D8C6A4",
    "wall":        "#F2EEE5",
    "wall_dark":   "#D4CDBF",
    "rock":        "#8C7E72",
    "rock_deep":   "#6B5C52",
    "core_water":  "#3FB3B0",
    "core_rim":    "#EDE7DA",
    "obstacle":    "#7D726B",
    "enemy":       "#E24A7B",
    "trap_spikes": "#C9C2B4",
    "trap_tar":    "#7FA860",
    "trap_launch": "#F0B23C",
    "trap_push":   "#8E7BC4",
    "trap_saw":    "#D2453F",
    "cloud":       "#EAF1F0",
    "sky_top":     "#A6C4C2",
    "sky_bottom":  "#E1EBE7",

    "rock_depth_min": 2.2,      # 岩体最短
    "rock_depth_max": 7.0,      # 岩体最长（做出不规则垂坠感）
    "rock_taper": 0.45,         # 底部收缩比例
    "rock_jitter": 0.55,        # 底部随机偏移
    "bevel_width": 0.05,
    "sun_energy": 2.6,
    "sun_angle_deg": 14.0,      # 太阳角直径越大阴影越软
    "world_strength": 0.55,
    "fog_color":   "#D4E2DE",   # 远处褪向这个雾色（用合成器的 Mist 遮罩做）
    "mist_start":  118.0,       # 摄像机在 120 远处，所以雾从岛的中后段开始
    "mist_depth":  120.0,
    "mist_amount": 0.92,
    "fog_strength": 0.9,
    "seed": 20260911,
    "exposure": -0.12,
    "view_transform": "Standard",
    "look": "None",
}

# 演示场景里那套杀戮区（和 tests/demo.gd 一致），让渲染图就是我们真正的场景
DEMO_TRAPS = [
    ("tar",       (6, 11), (0, -1)),
    ("tar",       (7, 11), (0, -1)),
    ("spikes",    (6, 12), (0, -1)),
    ("spikes",    (7, 12), (0, -1)),
    ("push_wall", (5, 9),  (1, 0)),
    ("saw",       (8, 9),  (-1, 0)),
    ("launcher",  (6, 14), (0, -1)),
]

# 摆几个敌人占位，体现"成堆涌入"
DEMO_ENEMIES = [
    (6, 18), (7, 18), (8, 17), (6, 16), (7, 15),
    (6, 13), (7, 13), (6, 10), (7, 9),
]

VOID, FLOOR, WALL, OBSTACLE, BRIDGE, CORE = 0, 1, 2, 3, 4, 5


# ----------------------------------------------------------------- 工具

def srgb(hex_str, alpha=1.0):
    """#RRGGBB -> Blender 线性色"""
    h = hex_str.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2], alpha)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    args = {"project": ".", "level": "corridor_01", "out": "renders/island.png",
            "width": 1600, "height": 900, "samples": 64}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key in args and i + 1 < len(argv):
            val = argv[i + 1]
            args[key] = int(val) if key in ("width", "height", "samples") else val
            i += 2
        else:
            i += 1
    return args


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name, hex_color, roughness=0.9, emission=None, fog=True):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = srgb(hex_color)
    bsdf.inputs["Roughness"].default_value = roughness
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    for socket in ("Specular IOR Level", "Specular"):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = 0.15
    if emission is not None and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = srgb(emission)
        bsdf.inputs["Emission Strength"].default_value = 0.35
    if fog:
        _add_depth_fog(mat)
    return mat


def _add_depth_fog(mat):
    """按到摄像机的深度把材质混向雾色 —— 远处褪进天空，撑出"悬在云上"的空气感"""
    amount = STYLE.get("mist_amount", 0.0)
    if amount <= 0.0:
        return
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    out = nt.nodes.get("Material Output")
    if bsdf is None or out is None:
        return
    cam = nt.nodes.new("ShaderNodeCameraData")
    rng_node = nt.nodes.new("ShaderNodeMapRange")
    rng_node.clamp = True
    rng_node.inputs["From Min"].default_value = STYLE["mist_start"]
    rng_node.inputs["From Max"].default_value = STYLE["mist_start"] + STYLE["mist_depth"]
    rng_node.inputs["To Min"].default_value = 0.0
    rng_node.inputs["To Max"].default_value = amount
    emi = nt.nodes.new("ShaderNodeEmission")
    emi.inputs["Color"].default_value = srgb(STYLE["fog_color"])
    emi.inputs["Strength"].default_value = STYLE.get("fog_strength", 0.9)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(cam.outputs["View Z Depth"], rng_node.inputs["Value"])
    nt.links.new(rng_node.outputs["Result"], mix.inputs["Fac"])
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emi.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])


def add_mesh(name, verts, faces, material, face_mats=None, collection=None):
    """脚本内部一律用 (x, up, depth) 描述（和游戏的 Y-up 一致），
    这里统一转成 Blender 的 Z-up (x, y, z)。
    material 可以是单个材质，也可以是材质列表 + 每面的材质下标 face_mats。"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(v[0], v[2], v[1]) for v in verts], [], faces)
    mesh.update()
    mats = material if isinstance(material, (list, tuple)) else [material]
    for m in mats:
        mesh.materials.append(m)
    if face_mats:
        for poly, idx in zip(mesh.polygons, face_mats):
            poly.material_index = idx
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def box(cx, cz, y0, y1, sx, sz, jitter_bottom=None):
    """轴对齐盒子。jitter_bottom=(scale, dx, dz) 时底面收缩并偏移，做出岩柱的锥形。"""
    hx, hz = sx * 0.5, sz * 0.5
    top = [(cx - hx, y1, cz - hz), (cx + hx, y1, cz - hz),
           (cx + hx, y1, cz + hz), (cx - hx, y1, cz + hz)]
    if jitter_bottom:
        s, dx, dz = jitter_bottom
        bx, bz = cx + dx, cz + dz
        bhx, bhz = hx * s, hz * s
    else:
        bx, bz, bhx, bhz = cx, cz, hx, hz
    bottom = [(bx - bhx, y0, bz - bhz), (bx + bhx, y0, bz - bhz),
              (bx + bhx, y0, bz + bhz), (bx - bhx, y0, bz + bhz)]
    verts = top + bottom
    faces = [(0, 1, 2, 3), (7, 6, 5, 4),
             (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    return verts, faces


def merge(parts):
    """把 [(verts, faces), ...] 合成一个网格的顶点/面列表"""
    verts, faces = [], []
    for v, f in parts:
        off = len(verts)
        verts.extend(v)
        faces.extend([tuple(i + off for i in face) for face in f])
    return verts, faces


def top_side_mats(face_count):
    """box() 的面序是 [顶, 底, 侧, 侧, 侧, 侧]，顶面用 0 号材质、其余用 1 号"""
    out = []
    for i in range(face_count):
        out.append(0 if i % 6 == 0 else 1)
    return out


def bevel(obj, width=None, segments=2):
    m = obj.modifiers.new("Bevel", "BEVEL")
    m.width = width if width is not None else STYLE["bevel_width"]
    m.segments = segments
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(40)
    return obj


def cylinder(name, center, radius, y0, y1, material, sides=16, top_radius=None):
    top_radius = radius if top_radius is None else top_radius
    verts, faces = [], []
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((center[0] + math.cos(a) * radius, y0, center[1] + math.sin(a) * radius))
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((center[0] + math.cos(a) * top_radius, y1, center[1] + math.sin(a) * top_radius))
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, j + sides, i + sides))
    faces.append(tuple(range(sides - 1, -1, -1)))
    faces.append(tuple(range(sides, sides * 2)))
    return add_mesh(name, verts, faces, material)


def ring(name, center, r_in, r_out, y0, y1, material, sides=28):
    """环形柱体（池沿）"""
    verts, faces = [], []
    for rad, yy in ((r_out, y0), (r_out, y1), (r_in, y1), (r_in, y0)):
        for i in range(sides):
            a = 2 * math.pi * i / sides
            verts.append((center[0] + math.cos(a) * rad, yy, center[1] + math.sin(a) * rad))
    def quad(ring_a, ring_b):
        for i in range(sides):
            j = (i + 1) % sides
            faces.append((ring_a * sides + i, ring_a * sides + j,
                          ring_b * sides + j, ring_b * sides + i))
    quad(0, 1); quad(1, 2); quad(2, 3); quad(3, 0)
    return add_mesh(name, verts, faces, material)


def pawn(name, center, radius, height, material):
    """圆头小兵占位：圆柱 + 半球顶"""
    sides, rings = 14, 5
    verts, faces = [], []
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((center[0] + math.cos(a) * radius, 0.0, center[1] + math.sin(a) * radius))
    body_top = height - radius
    for i in range(sides):
        a = 2 * math.pi * i / sides
        verts.append((center[0] + math.cos(a) * radius, body_top, center[1] + math.sin(a) * radius))
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, j + sides, i + sides))
    faces.append(tuple(range(sides - 1, -1, -1)))
    prev_ring = list(range(sides, sides * 2))
    for r in range(1, rings + 1):
        phi = (math.pi * 0.5) * r / rings
        rr, yy = radius * math.cos(phi), body_top + radius * math.sin(phi)
        ring = []
        for i in range(sides):
            a = 2 * math.pi * i / sides
            ring.append(len(verts))
            verts.append((center[0] + math.cos(a) * rr, yy, center[1] + math.sin(a) * rr))
        for i in range(sides):
            j = (i + 1) % sides
            faces.append((prev_ring[i], prev_ring[j], ring[j], ring[i]))
        prev_ring = ring
    faces.append(tuple(prev_ring))
    return add_mesh(name, verts, faces, material)


# ----------------------------------------------------------------- 搭场景

def sync_style_with_game(project):
    """配色和岩体参数以 data/art.json 为准，避免游戏和渲染两边各写一份"""
    path = os.path.join(project, "data", "art.json")
    if not os.path.exists(path):
        print("ART_JSON_MISSING %s（用脚本内置配色）" % path)
        return
    with open(path, encoding="utf-8") as f:
        art = json.load(f)
    pal = art.get("palette", {})
    tops = pal.get("floor_top", [])
    for i, key in enumerate(("floor_top", "floor_top_b", "floor_top_c")):
        if i < len(tops):
            STYLE[key] = tops[i]
    for src, dst in (("floor_side", "floor_side"), ("bridge_top", "bridge"),
                     ("wall_top", "wall"), ("wall_side", "wall_dark"),
                     ("rock_top", "rock"), ("rock_deep", "rock_deep"),
                     ("obstacle_top", "obstacle"), ("core_rim", "core_rim"),
                     ("core_water", "core_water"), ("cloud", "cloud")):
        if src in pal:
            STYLE[dst] = pal[src]
    rock = art.get("rock", {})
    for src, dst in (("edge_depth_min", "rock_depth_min"), ("edge_depth_max", "rock_depth_max"),
                     ("taper", "rock_taper"), ("jitter", "rock_jitter"), ("seed", "seed")):
        if src in rock:
            STYLE[dst] = rock[src]
    print("STYLE_SYNCED_FROM data/art.json")


def build(args):
    project = os.path.abspath(args["project"])
    sync_style_with_game(project)
    with open(os.path.join(project, "data", "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(project, "data", "levels", "%s.json" % args["level"]), encoding="utf-8") as f:
        level = json.load(f)

    cs = float(cfg["grid"]["cell_size"])
    wall_h = float(cfg["grid"]["wall_height"])
    thick = float(cfg["grid"]["floor_thickness"])
    rows = level["grid"]
    h, w = len(rows), len(rows[0])
    rng = random.Random(STYLE["seed"])

    clear_scene()
    scene = bpy.context.scene

    mats = {k: make_material(k, v) for k, v in STYLE.items() if isinstance(v, str) and v.startswith("#")}
    mats["core_water"] = make_material("core_water", STYLE["core_water"], roughness=0.15,
                                       emission=STYLE["core_water"])

    def cell(x, y):
        if 0 <= x < w and 0 <= y < h:
            return int(rows[y][x])
        return VOID

    def cx(x):
        return (x + 0.5) * cs

    def cz(y):
        return (y + 0.5) * cs

    # --- 顶面板：地面 / 核心 / 桥
    floor_parts, bridge_parts, floor_tops = [], [], []
    for y in range(h):
        for x in range(w):
            t = cell(x, y)
            if t in (FLOOR, CORE, WALL, OBSTACLE):
                floor_parts.append(box(cx(x), cz(y), -thick, 0.0, cs, cs))
                r = rng.random()
                floor_tops.append(0 if r < 0.62 else (1 if r < 0.88 else 2))
            elif t == BRIDGE:
                bridge_parts.append(box(cx(x), cz(y), -thick * 0.7, 0.0, cs * 0.94, cs * 0.94))
    fv, ff = merge(floor_parts)
    floor_face_mats = []
    for i in range(len(ff)):
        floor_face_mats.append(floor_tops[i // 6] if i % 6 == 0 else 3)
    bevel(add_mesh("Floor", fv, ff,
                   [mats["floor_top"], mats["floor_top_b"], mats["floor_top_c"], mats["floor_side"]],
                   face_mats=floor_face_mats), 0.04)
    if bridge_parts:
        bv, bf = merge(bridge_parts)
        bevel(add_mesh("Bridge", bv, bf, [mats["bridge"], mats["floor_side"]],
                       face_mats=top_side_mats(len(bf))), 0.04)

    # --- 岛底岩体：每个实心格向下长一根带锥度的岩柱，长度随机 -> 不规则垂坠
    rock_parts = []
    for y in range(h):
        for x in range(w):
            if cell(x, y) in (VOID, BRIDGE):
                continue
            edge = any(cell(x + dx, y + dy) in (VOID, BRIDGE)
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            border = x in (0, w - 1) or y in (0, h - 1)
            depth = rng.uniform(STYLE["rock_depth_min"], STYLE["rock_depth_max"]) \
                if (edge or border) else rng.uniform(1.2, 2.4)
            jitter = STYLE["rock_jitter"]
            rock_parts.append(box(
                cx(x), cz(y), -thick - depth, -thick + 0.01, cs, cs,
                jitter_bottom=(STYLE["rock_taper"] * rng.uniform(0.7, 1.5),
                               rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter))))
    rv, rf = merge(rock_parts)
    add_mesh("Rock", rv, rf, [mats["rock"], mats["rock_deep"]],
             face_mats=[0 if i % 6 == 0 else 1 for i in range(len(rf))])

    # --- 墙
    wall_parts = []
    for y in range(h):
        for x in range(w):
            if cell(x, y) == WALL:
                wall_parts.append(box(cx(x), cz(y), 0.0, wall_h, cs * 0.99, cs * 0.99))
    if wall_parts:
        wv, wf = merge(wall_parts)
        bevel(add_mesh("Walls", wv, wf, [mats["wall"], mats["wall_dark"]],
                       face_mats=top_side_mats(len(wf))), 0.07, 3)

    # --- 障碍：矮岩块
    obs_parts = []
    for y in range(h):
        for x in range(w):
            if cell(x, y) == OBSTACLE:
                obs_parts.append(box(cx(x), cz(y), 0.0, wall_h * 1.3, cs * 0.75, cs * 0.75,
                                     jitter_bottom=None))
    if obs_parts:
        bevel(add_mesh("Obstacles", *merge(obs_parts), material=mats["obstacle"]), 0.08, 2)

    # --- 核心：参考图里的水池，用青色水面 + 奶白池沿
    cores = [(x, y) for y in range(h) for x in range(w) if cell(x, y) == CORE]
    if cores:
        ccx = sum(cx(x) for x, _ in cores) / len(cores)
        ccz = sum(cz(y) for _, y in cores) / len(cores)
        bevel(ring("CoreRim", (ccx, ccz), cs * 0.72, cs * 0.95, 0.0, 0.40, mats["core_rim"]), 0.03)
        cylinder("CoreWater", (ccx, ccz), cs * 0.73, 0.02, 0.30, mats["core_water"], sides=28)

    # --- 机关占位
    trap_colors = {"spikes": "trap_spikes", "tar": "trap_tar", "launcher": "trap_launch",
                   "push_wall": "trap_push", "saw": "trap_saw"}
    for tid, (x, y), (fx, fy) in DEMO_TRAPS:
        mat = mats[trap_colors[tid]]
        if tid in ("spikes", "tar", "launcher"):
            verts, faces = box(cx(x), cz(y), 0.01, 0.14 if tid != "launcher" else 0.22,
                               cs * 0.82, cs * 0.82)
            bevel(add_mesh("Trap_%s_%d_%d" % (tid, x, y), verts, faces, mat), 0.03)
        else:
            # 墙面机关：贴在墙的暴露面上
            px, pz = cx(x) + fx * cs * 0.5, cz(y) + fy * cs * 0.5
            sx = 0.22 if fx else cs * 0.7
            sz = cs * 0.7 if fx else 0.22
            verts, faces = box(px, pz, wall_h * 0.25, wall_h * 0.85, sx, sz)
            bevel(add_mesh("Trap_%s_%d_%d" % (tid, x, y), verts, faces, mat), 0.04)

    # --- 敌人占位
    for x, y in DEMO_ENEMIES:
        jx, jz = rng.uniform(-0.35, 0.35), rng.uniform(-0.35, 0.35)
        pawn("Enemy_%d_%d" % (x, y), (cx(x) + jx, cz(y) + jz), 0.36, 1.15, mats["enemy"])

    # --- 云：岛下方几团压扁的低模球，把"悬空"感撑起来
    cx0, cz0 = w * cs * 0.5, h * cs * 0.5
    cloud_mat = make_material("cloud_near", STYLE["cloud"], roughness=1.0, fog=False)
    for i in range(20):
        r = rng.uniform(6.0, 13.0)
        px = cx0 + rng.uniform(-2.6, 2.6) * cx0
        py = cz0 + rng.uniform(-2.6, 2.6) * cz0
        pz = rng.uniform(-38.0, -14.0)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r, location=(px, py, pz))
        obj = bpy.context.active_object
        obj.name = "Cloud_%d" % i
        obj.scale = (1.0, rng.uniform(0.75, 1.3), rng.uniform(0.13, 0.22))
        obj.data.materials.append(cloud_mat)
        for poly in obj.data.polygons:     # 云要圆润，不能是水晶块
            poly.use_smooth = True

    setup_world(scene)
    setup_camera_and_light(scene, cfg, w, h, cs)
    return scene


def setup_world(scene):
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = STYLE["world_strength"]
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = srgb(STYLE["sky_bottom"])
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = srgb(STYLE["sky_top"])
    texco = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(texco.outputs["Window"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])




def setup_camera_and_light(scene, cfg, w, h, cs):
    cam_cfg = cfg["camera"]
    # 游戏里 pitch 是负数（往下看），这里换算成仰角
    elev = math.radians(abs(float(cam_cfg["pitch_deg"])))
    yaw = math.radians(float(cam_cfg["yaw_deg"]))
    pivot = Vector((w * cs * 0.5, h * cs * 0.5, 0.0))    # Blender: Z 向上
    dist = 120.0
    offset = Vector((math.cos(elev) * math.sin(yaw) * dist,
                     -math.cos(elev) * math.cos(yaw) * dist,
                     math.sin(elev) * dist))

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = float(cam_cfg.get("ortho_size", 46.0)) * 1.12
    cam_data.clip_start = 1.0
    cam_data.clip_end = 400.0
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = pivot + offset
    direction = (pivot - cam.location).normalized()
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = STYLE["sun_energy"]
    sun_data.angle = math.radians(STYLE["sun_angle_deg"])
    sun_data.color = (1.0, 0.97, 0.92)
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.location = pivot + Vector((-30.0, -40.0, 60.0))
    sun.rotation_euler = (Vector((0.62, 0.60, -0.62)).normalized()
                          .to_track_quat("-Z", "Y").to_euler())
    scene.collection.objects.link(sun)

    fill_data = bpy.data.lights.new("Fill", type="SUN")
    fill_data.energy = 0.9
    fill_data.angle = math.radians(30.0)
    fill_data.color = srgb(STYLE["sky_top"])[:3]
    fill = bpy.data.objects.new("Fill", fill_data)
    fill.rotation_euler = (Vector((-0.6, -0.4, -0.7)).normalized()
                           .to_track_quat("-Z", "Y").to_euler())
    scene.collection.objects.link(fill)


def render(scene, args):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = args["width"]
    scene.render.resolution_y = args["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    ee = scene.eevee
    for attr, val in (("taa_render_samples", args["samples"]),
                      ("use_shadows", True),
                      ("use_raytracing", True),
                      ("use_shadow_jitter_viewport", True),
                      ):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    if hasattr(scene, "view_settings"):
        # 平涂粉彩风格用 Standard 更接近参考图；AgX 会把颜色压灰
        scene.view_settings.view_transform = STYLE.get("view_transform", "Standard")
        scene.view_settings.exposure = STYLE.get("exposure", -0.25)
        look = STYLE.get("look", "None")
        try:
            scene.view_settings.look = look
        except TypeError:
            scene.view_settings.look = "None"

    out = os.path.abspath(os.path.join(args["project"], args["out"]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("RENDERED %s" % out)


if __name__ == "__main__":
    a = parse_args()
    render(build(a), a)
