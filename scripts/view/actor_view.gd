class_name ActorView
extends Node3D
## 敌人模型 + 程序化动作。模型里没有骨骼，各部件的原点就放在关节上
## （颈/肩/髋/握把），这里直接给节点转角度做跑步和倒地。

const MODEL_DIR := "res://assets/models/"
const PART_NAMES := ["Torso", "Head", "ArmL", "ArmR", "LegL", "LegR", "Sword", "Shield"]

static var _scene_cache: Dictionary = {}

var parts: Dictionary = {}          # 名字 -> Node3D
var rest: Dictionary = {}           # 名字 -> 静止姿势的 transform
var model_root: Node3D = null
var model_id := ""
var ok := false

var _tint_mats: Array[StandardMaterial3D] = []
var _shade_mats: Array[StandardMaterial3D] = []
var _base_color := Color.WHITE
var _leg_swing := 57.0
var _arm_swing := 60.0
var _sword_arm_ratio := 0.55
var _torso_lean := 14.0
var _head_lean := 4.0
var _bob := 0.06
var _locked_arms: Array = []
var _shade_darken := 0.42
var _height := 1.0
var _marker: MeshInstance3D = null
var _marker_mat: StandardMaterial3D = null
var _marker_alpha := 0.85
var _marker_color := Color.WHITE
var _sword_free := false
var _sword_vel := Vector3.ZERO
var _sword_spin := Vector3.ZERO

# ---------------------------------------------------------------- 载入

func setup(p_model_id: String, height: float, color: Color) -> bool:
	model_id = p_model_id
	var path := MODEL_DIR + model_id + ".glb"
	if not _scene_cache.has(path):
		_scene_cache[path] = load(path) if ResourceLoader.exists(path) else null
	var packed = _scene_cache[path]
	if packed == null:
		return false
	model_root = packed.instantiate()
	add_child(model_root)
	_height = height
	model_root.scale = Vector3.ONE * height      # 模型本体做成 1.0 高，按敌人身高缩放

	for n in PART_NAMES:
		var node := _find(model_root, n)
		if node != null:
			parts[n] = node
			rest[n] = node.transform
	_load_anim_params()
	_build_marker(color)
	_collect_tint_materials(model_root)
	set_color(color)
	ok = parts.has("LegL") and parts.has("LegR")
	return ok

## 动作参数放在 data/art.json 的 anim 段，改完 F5 就能试
func _load_anim_params() -> void:
	var a: Dictionary = Cfg.art.get("anim", {}).duplicate()
	# 按模型覆盖：盾兵上身更直、左臂托盾不摆
	var per: Dictionary = Cfg.art.get("anim", {}).get("per_model", {}).get(model_id, {})
	for k in per.keys():
		a[k] = per[k]
	_locked_arms = a.get("lock_arms", [])
	_shade_darken = float(a.get("shade_darken", _shade_darken))
	_leg_swing = float(a.get("leg_swing_deg", _leg_swing))
	_arm_swing = float(a.get("arm_swing_deg", _arm_swing))
	_sword_arm_ratio = float(a.get("sword_arm_ratio", _sword_arm_ratio))
	_torso_lean = float(a.get("torso_lean_deg", _torso_lean))
	_head_lean = float(a.get("head_lean_deg", _head_lean))
	_bob = float(a.get("bob_height", _bob))

func _find(node: Node, name: String) -> Node3D:
	if node.name == name and node is Node3D:
		return node
	for c in node.get_children():
		var r := _find(c, name)
		if r != null:
			return r
	return null

## 地面标记：拉远时单位只有几个像素，靠这个圆点保证看得见
func _build_marker(color: Color) -> void:
	var cfg: Dictionary = Cfg.art.get("zoom_readability", {})
	if not bool(cfg.get("enabled", true)):
		return
	_marker_alpha = float(cfg.get("marker_alpha", 0.85))
	var r: float = _height * 0.5 * float(cfg.get("marker_radius_mul", 1.9))
	var disc := CylinderMesh.new()
	disc.top_radius = r
	disc.bottom_radius = r
	disc.height = 0.05
	disc.radial_segments = 18
	_marker_mat = StandardMaterial3D.new()
	# 比本体再亮一点，压在地面上才跳得出来
	var c: Color = color.lightened(0.15)
	_marker_color = Color(c.r, c.g, c.b, 1.0)
	_marker_mat.albedo_color = Color(c.r, c.g, c.b, 0.0)
	_marker_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_marker_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_marker = MeshInstance3D.new()
	_marker.name = "GroundMarker"
	_marker.mesh = disc
	_marker.material_override = _marker_mat
	_marker.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_marker.position.y = 0.04
	_marker.visible = false
	add_child(_marker)

## 每帧由敌人传进来：拉得越远单位放得越大、地面标记越明显
func apply_view(unit_scale: float, marker: float) -> void:
	if model_root != null:
		model_root.scale = Vector3.ONE * (_height * unit_scale)
	if _marker == null:
		return
	if marker <= 0.01:
		_marker.visible = false
		return
	_marker.visible = true
	_marker.scale = Vector3(marker, 1.0, marker)
	# 注意：不能写 albedo_color.a = x —— 属性返回的是副本，改了不会写回材质
	var mc: Color = _marker_color
	mc.a = _marker_alpha * marker
	_marker_mat.albedo_color = mc

func hide_marker() -> void:
	if _marker != null:
		_marker.visible = false

## 主色（armor_primary）按敌人类型换色；其余配色沿用模型自带的
func _collect_tint_materials(node: Node) -> void:
	if node is MeshInstance3D:
		var mesh: Mesh = node.mesh
		if mesh != null:
			for i in mesh.get_surface_count():
				var m := mesh.surface_get_material(i)
				if m == null:
					continue
				var mname := String(m.resource_name)
				if mname.begins_with("armor_primary") or mname.begins_with("armor_shade"):
					var dup: StandardMaterial3D = m.duplicate()
					node.set_surface_override_material(i, dup)
					# armor_shade 是腿和护手，跟着主色但暗一档
					if mname.begins_with("armor_shade"):
						_shade_mats.append(dup)
					else:
						_tint_mats.append(dup)
	for c in node.get_children():
		_collect_tint_materials(c)

func set_color(c: Color) -> void:
	_base_color = c
	_apply_tint(c)

func _apply_tint(c: Color) -> void:
	for m in _tint_mats:
		m.albedo_color = c
	var dark: Color = c.darkened(_shade_darken)
	for m in _shade_mats:
		m.albedo_color = dark

## 受伤变暗、减速泛蓝，和原来的胶囊表现一致
func set_state_tint(hp_ratio: float, slowed: bool) -> void:
	var c: Color = _base_color.lerp(Color(0.35, 0.05, 0.05), 1.0 - clampf(hp_ratio, 0.0, 1.0))
	if slowed:
		c = c.lerp(Color(0.3, 0.6, 1.0), 0.35)
	_apply_tint(c)

# ---------------------------------------------------------------- 动作

## 在静止姿势的基础上再叠一个旋转（用于抵消父节点的摆动）
func _rot_compose(part: String, euler: Vector3) -> void:
	if not parts.has(part):
		return
	var n: Node3D = parts[part]
	var t: Transform3D = rest[part]
	n.transform = Transform3D(t.basis * Basis.from_euler(euler), t.origin)

func _rot(part: String, euler: Vector3) -> void:
	if not parts.has(part):
		return
	var n: Node3D = parts[part]
	var t: Transform3D = rest[part]
	n.transform = Transform3D(Basis.from_euler(euler), t.origin)

## phase 随走过的距离推进；intensity 0=站定 1=全速
func set_run(phase: float, intensity: float) -> void:
	var sw: float = deg_to_rad(_leg_swing) * intensity
	var aw: float = deg_to_rad(_arm_swing) * intensity
	var s := sin(phase)
	_rot("LegL", Vector3(s * sw, 0, 0))
	_rot("LegR", Vector3(-s * sw, 0, 0))
	if not _locked_arms.has("ArmL"):
		_rot("ArmL", Vector3(-s * aw, 0, deg_to_rad(6.0)))
	# 持剑那条手臂摆幅小一些，剑跟着甩太厉害会看不清朝向
	if not _locked_arms.has("ArmR"):
		_rot("ArmR", Vector3(s * aw * _sword_arm_ratio, 0, -deg_to_rad(6.0)))
	# 剑反向抵消手臂的摆动：等距相机下剑一旦偏离竖直就会被压扁成横的，
	# 不同朝向看起来就像"剑一会朝上一会朝下"
	if not _sword_free:
		_rot_compose("Sword", Vector3(-s * aw, 0, 0))
	# 负角才是前倾：绕 +X 转会把"上"带向 +Z，而角色的前方是 -Z
	_rot("Torso", Vector3(-deg_to_rad(_torso_lean) * intensity, 0, 0))
	_rot("Head", Vector3(-deg_to_rad(_head_lean) * intensity, 0, 0))
	_stabilize_sword()
	if model_root != null:
		# 两条腿各迈一步 = 一个上下起伏周期
		model_root.position.y = absf(sin(phase)) * _bob * intensity

## 手臂摆动时把剑锁回静止朝向。
## 不能简单地"绕某个轴反向转同样角度" —— glTF 转 Y-up 之后剑的局部轴和手臂的
## 摆动轴对不上，那样转反而会再加一次摆幅（实测剑会偏离竖直 40 度）。
## 这里直接用矩阵算：让剑的世界朝向等于"手臂没摆动时"的朝向。
func _stabilize_sword() -> void:
	if _sword_free or not parts.has("Sword") or not parts.has("ArmR"):
		return
	var arm: Node3D = parts["ArmR"]
	var sw_rest: Transform3D = rest["Sword"]
	var b: Basis = arm.transform.basis.inverse() * (rest["ArmR"] as Transform3D).basis * sw_rest.basis
	(parts["Sword"] as Node3D).transform = Transform3D(b, sw_rest.origin)

func set_idle() -> void:
	set_run(0.0, 0.0)

## 被击飞时缩成一团，比僵直地保持跑步姿势可读
func set_tumble(t: float) -> void:
	var a := deg_to_rad(45.0)
	_rot("LegL", Vector3(-a, 0, deg_to_rad(10)))
	_rot("LegR", Vector3(-a * 0.7, 0, -deg_to_rad(10)))
	if not _locked_arms.has("ArmL"):
		_rot("ArmL", Vector3(-a * 1.4, 0, deg_to_rad(25)))
	_rot("ArmR", Vector3(-a * 1.2, 0, -deg_to_rad(25)))
	_rot("Torso", Vector3(deg_to_rad(20), 0, 0))
	if model_root != null:
		model_root.position.y = 0.0
		model_root.rotation.z = sin(t * 6.0) * 0.15

## 死亡：丢剑 + 四肢摊平。t 从 0 到 1。
func set_death(t: float) -> void:
	hide_marker()
	if not _sword_free:
		_release_sword()
	var e: float = 1.0 - pow(1.0 - clampf(t, 0.0, 1.0), 3.0)    # 先快后慢
	if model_root != null:
		model_root.rotation.x = -PI * 0.5 * e                     # 仰面倒下
		model_root.position.y = 0.0
	_rot("LegL", Vector3(deg_to_rad(10) * e, 0, deg_to_rad(28) * e))
	_rot("LegR", Vector3(deg_to_rad(6) * e, 0, -deg_to_rad(24) * e))
	_rot("ArmL", Vector3(deg_to_rad(12) * e, 0, deg_to_rad(75) * e))
	_rot("ArmR", Vector3(deg_to_rad(8) * e, 0, -deg_to_rad(70) * e))
	_rot("Torso", Vector3(-deg_to_rad(8) * e, 0, 0))
	_rot("Head", Vector3(-deg_to_rad(18) * e, 0, 0))

## 把剑从手上解绑，挂到场景里自己飞出去落地
func _release_sword() -> void:
	_sword_free = true
	if not parts.has("Sword"):
		return
	var sword: Node3D = parts["Sword"]
	var world := sword.global_transform
	sword.get_parent().remove_child(sword)
	add_child(sword)
	sword.global_transform = world
	var rng := RandomNumberGenerator.new()
	rng.seed = int(get_instance_id()) & 0x7fffffff
	_sword_vel = Vector3(rng.randf_range(-1.6, 1.6), rng.randf_range(2.2, 3.4), rng.randf_range(-1.6, 1.6))
	_sword_spin = Vector3(rng.randf_range(-8, 8), rng.randf_range(-6, 6), rng.randf_range(-8, 8))

func step_sword(dt: float, gravity: float) -> void:
	if not _sword_free or not parts.has("Sword"):
		return
	var sword: Node3D = parts["Sword"]
	if not is_instance_valid(sword):
		return
	_sword_vel.y -= gravity * dt
	sword.position += _sword_vel * dt
	sword.rotation += _sword_spin * dt
	if sword.position.y <= 0.06:
		sword.position.y = 0.06
		_sword_vel = Vector3.ZERO
		_sword_spin = Vector3.ZERO
