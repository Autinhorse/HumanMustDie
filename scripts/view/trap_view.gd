class_name TrapView
extends Node3D
## 机关模型 + 触发动作。和角色一样不做骨骼：模型里活动部件单独命名，
## 这里按 traps.json 的 anim 段驱动它的位移/旋转。
##
## anim 支持四种：
##   slide  沿轴平移（地刺伸缩、推墙推出）
##   rotate 绕轴转到某个角度（弹射板翻起）
##   spin   绕轴持续转（锯片）
##   bob    绕静止位置来回浮动（黏胶起伏）
##
## 触发动作分三段：attack 弹出、hold 停留、release 收回。

const MODEL_DIR := "res://assets/models/"

static var _scene_cache: Dictionary = {}

var model_root: Node3D = null
var part: Node3D = null
var ok := false

var _rest: Transform3D = Transform3D.IDENTITY
var _cfg: Dictionary = {}
var _kind := ""
var _axis := Vector3.UP
var _rest_v := 0.0
var _fire_v := 0.0
var _attack := 0.06
var _hold := 0.12
var _release := 0.3
var _spin_speed := 0.0
var _bob_amount := 0.0
var _bob_speed := 1.0

var _fire_t := 999.0        # 距离上次触发过了多久
var _time := 0.0
var _tint_mats: Array[StandardMaterial3D] = []
var _tint_base: Array[Color] = []
## 模型自带配色（面板那套）时不按 traps.json 的 color 换色
var keeps_own_color := false

## traps.json 的一条机关数据 -> 模型文件名。tier 只是名字后缀：
## board_spikes + tier 2 -> board_spikes_2。游戏和测试都走这里，
## 免得两边各算各的（T7 抓到过一次）。
static func model_for(data: Dictionary) -> String:
	var id := String(data.get("model", ""))
	if id != "" and data.has("tier"):
		id += "_%d" % int(Cfg.dget(data, "tier", 1.0))
	return id

func setup(model_id: String, cell_size: float, color: Color, anim: Dictionary) -> bool:
	keeps_own_color = model_id.begins_with("board_")
	var path := MODEL_DIR + model_id + ".glb"
	if not _scene_cache.has(path):
		_scene_cache[path] = load(path) if ResourceLoader.exists(path) else null
	var packed = _scene_cache[path]
	if packed == null:
		return false
	model_root = packed.instantiate()
	add_child(model_root)
	model_root.scale = Vector3.ONE * cell_size      # 模型按 1×1 格建，这里放大到实际格子

	_cfg = anim
	_kind = String(anim.get("type", ""))
	var axis: Array = anim.get("axis", [0, 1, 0])
	_axis = Vector3(float(axis[0]), float(axis[1]), float(axis[2])).normalized()
	_rest_v = float(anim.get("rest", 0.0))
	_fire_v = float(anim.get("fire", 0.0))
	_attack = float(anim.get("attack", 0.06))
	_hold = float(anim.get("hold", 0.12))
	_release = float(anim.get("release", 0.3))
	_spin_speed = float(anim.get("speed", 8.0))
	_bob_amount = float(anim.get("amount", 0.02))
	_bob_speed = float(anim.get("speed", 1.5))

	var part_name := String(anim.get("part", ""))
	if part_name != "":
		part = _find(model_root, part_name)
		if part != null:
			_rest = part.transform
	_collect_tint(model_root)
	if not keeps_own_color:
		set_color(color)
	_apply(0.0)
	ok = true
	return true

func _find(node: Node, name: String) -> Node3D:
	if node.name == name and node is Node3D:
		return node
	for c in node.get_children():
		var r := _find(c, name)
		if r != null:
			return r
	return null

## 收集可变色的材质。老的机械机关叫 trap_primary，按 traps.json 的 color 换色；
## 面板（board_*）的等级色是烘在模型里的，只收进来做冷却压暗，不换色。
func _collect_tint(node: Node) -> void:
	if node is MeshInstance3D:
		var mesh: Mesh = node.mesh
		if mesh != null:
			for i in mesh.get_surface_count():
				var m := mesh.surface_get_material(i)
				if m == null:
					continue
				var rn := String(m.resource_name)
				if rn.begins_with("trap_primary") or rn.begins_with("board_accent"):
					var dup: StandardMaterial3D = m.duplicate()
					node.set_surface_override_material(i, dup)
					_tint_mats.append(dup)
					_tint_base.append(dup.albedo_color)
	for c in node.get_children():
		_collect_tint(c)

func set_color(c: Color) -> void:
	for i in _tint_mats.size():
		_tint_mats[i].albedo_color = c
		_tint_base[i] = c

## 冷却时压暗。面板的等级色不能被换掉，所以这里是在**原色基础上**压暗，
## 而不是像老机关那样整个换成冷却色。
func set_dim(f: float) -> void:
	var k: float = clampf(f, 0.0, 1.0)
	for i in _tint_mats.size():
		_tint_mats[i].albedo_color = _tint_base[i].lerp(Color(0.34, 0.34, 0.38), k)

func _process(delta: float) -> void:
	# 自己驱动：待机动作在建造阶段也要动，不能只在战斗里跑
	step(delta)

## 机关触发时调一次，动作从头播
func fire() -> void:
	_fire_t = 0.0

func step(dt: float) -> void:
	_time += dt
	_fire_t += dt
	_apply(dt)

func _apply(dt: float) -> void:
	if part == null:
		return
	match _kind:
		"spin":
			part.transform = Transform3D(_rest.basis * Basis(_axis, _time * _spin_speed), _rest.origin)
		"bob":
			var off: float = sin(_time * _bob_speed) * _bob_amount
			part.transform = Transform3D(_rest.basis, _rest.origin + _axis * off)
		"slide":
			part.transform = Transform3D(_rest.basis, _rest.origin + _axis * _value())
		"rotate":
			part.transform = Transform3D(_rest.basis * Basis(_axis, deg_to_rad(_value())), _rest.origin)

## 触发动作的三段：弹出 -> 停留 -> 收回
func _value() -> float:
	var t := _fire_t
	if t < _attack:
		return lerpf(_rest_v, _fire_v, _ease_out(t / max(_attack, 0.0001)))
	if t < _attack + _hold:
		return _fire_v
	var r: float = (t - _attack - _hold) / max(_release, 0.0001)
	if r >= 1.0:
		return _rest_v
	return lerpf(_fire_v, _rest_v, _ease_in_out(r))

func _ease_out(x: float) -> float:
	return 1.0 - pow(1.0 - clampf(x, 0.0, 1.0), 3.0)

func _ease_in_out(x: float) -> float:
	x = clampf(x, 0.0, 1.0)
	return x * x * (3.0 - 2.0 * x)
