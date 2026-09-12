class_name Fx
extends Node3D
## 打击表现：火花、尘土、死亡爆散，外加镜头抖动。
##
## 模拟层不直接建粒子 —— Game 只往 fx_queue 里塞事件，main.gd 每帧取出来交给这里。
## 这样无头测试跑的还是纯逻辑，表现层加什么都不会动到定点步进的结果。
##
## 每种效果预先建好一小撮发射器轮流用（restart 比 new 便宜得多），
## 参数全在 art.json 的 fx 段里，改手感不用动代码。

const KINDS := ["hit", "launch", "land", "death", "fall"]

var _pools: Dictionary = {}        # kind -> Array[GPUParticles3D]
var _next: Dictionary = {}         # kind -> 轮到第几个
var _cfg: Dictionary = {}

# 镜头抖动：叠加的偏移量，自己按时间衰减
var shake: float = 0.0
var _shake_decay := 6.0
var _shake_freq := 34.0
var _shake_max := 0.6
var _t := 0.0
## 拉远时的放大系数，由 main.gd 按当前可视高度推给我们
var zoom_scale: float = 1.0

func setup(fx_cfg: Dictionary) -> void:
	_cfg = fx_cfg
	_shake_decay = float(fx_cfg.get("shake_decay", 6.0))
	_shake_freq = float(fx_cfg.get("shake_freq", 34.0))
	_shake_max = float(fx_cfg.get("shake_max", 0.6))
	var pool_size := int(fx_cfg.get("pool_size", 6))
	for kind in KINDS:
		var arr: Array[GPUParticles3D] = []
		for i in pool_size:
			var p := _make_emitter(kind)
			add_child(p)
			arr.append(p)
		_pools[kind] = arr
		_next[kind] = 0

func _k(kind: String, key: String, def: float) -> float:
	var d: Dictionary = _cfg.get(kind, {})
	return float(d.get(key, def))

func _make_emitter(kind: String) -> GPUParticles3D:
	var p := GPUParticles3D.new()
	p.emitting = false
	p.one_shot = true
	p.explosiveness = 1.0        # 一次性全喷出来，才是"打中了"而不是"在冒烟"
	p.local_coords = false
	p.amount = int(_k(kind, "amount", 12.0))
	p.lifetime = _k(kind, "lifetime", 0.4)
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

	var m := ParticleProcessMaterial.new()
	m.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	m.emission_sphere_radius = _k(kind, "radius", 0.12)
	m.spread = _k(kind, "spread", 55.0)
	m.initial_velocity_min = _k(kind, "speed", 3.0) * 0.5
	m.initial_velocity_max = _k(kind, "speed", 3.0)
	m.gravity = Vector3(0, -_k(kind, "gravity", 12.0), 0)
	m.damping_min = _k(kind, "damping", 1.0)
	m.damping_max = _k(kind, "damping", 1.0) * 2.0
	m.scale_min = _k(kind, "scale", 0.07) * 0.6
	m.scale_max = _k(kind, "scale", 0.07)
	# 收尾缩到 0，省得粒子"啪"地消失
	var curve := CurveTexture.new()
	var c := Curve.new()
	c.add_point(Vector2(0.0, 1.0))
	c.add_point(Vector2(0.65, 0.85))
	c.add_point(Vector2(1.0, 0.0))
	curve.curve = c
	m.scale_curve = curve
	# 同时淡出：只缩小的话小颗粒会在白地面上突然不见
	var ramp := GradientTexture1D.new()
	var g := Gradient.new()
	g.set_color(0, Color(1, 1, 1, 1))
	g.set_color(1, Color(1, 1, 1, 0))
	g.add_point(0.6, Color(1, 1, 1, 0.9))
	ramp.gradient = g
	m.color_ramp = ramp
	p.process_material = m

	var mesh: Mesh
	if kind == "hit" or kind == "death":
		# 火花用细长方块，飞出去有方向感，圆球看着像泡泡
		var bm := BoxMesh.new()
		bm.size = Vector3(0.35, 0.35, 1.0)
		mesh = bm
	else:
		var sm := SphereMesh.new()
		sm.radius = 0.5
		sm.height = 1.0
		sm.radial_segments = 6
		sm.rings = 3
		mesh = sm
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = false
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.blend_mode = BaseMaterial3D.BLEND_MODE_MIX
	# 不开 billboard：Godot 的 billboard 会重建基向量，把每颗粒子的缩放一起丢掉，
	# 结果所有粒子都按网格原始尺寸画出来（实测大了十几倍）。
	# 反正是固定角度的正交相机，低面数的球和方块本来就够看。
	mat.billboard_mode = BaseMaterial3D.BILLBOARD_DISABLED
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mesh.surface_set_material(0, mat)
	p.draw_pass_1 = mesh
	return p

## 放一发效果。dir 是冲击方向（没有就传零向量），power 0~1 控制强度。
func burst(kind: String, pos: Vector3, dir: Vector3, color: Color, power: float) -> void:
	if not _pools.has(kind):
		return
	var arr: Array = _pools[kind]
	if arr.is_empty():
		return
	var idx: int = int(_next[kind]) % arr.size()
	_next[kind] = idx + 1
	var p: GPUParticles3D = arr[idx]
	p.global_position = pos
	# 让粒子顺着冲击方向喷：没有方向就朝上
	var d := dir
	d.y += _k(kind, "up_bias", 0.6)
	if d.length() < 0.01:
		d = Vector3.UP
	var m: ParticleProcessMaterial = p.process_material
	m.direction = d.normalized()
	var pw: float = clampf(power, 0.15, 1.0)
	# 尺寸和初速一起按 zoom_scale 放大，只放大尺寸的话粒子会挤成一坨不散开
	var z: float = max(zoom_scale, 0.01)
	m.initial_velocity_min = _k(kind, "speed", 3.0) * 0.5 * pw * z
	m.initial_velocity_max = _k(kind, "speed", 3.0) * pw * z
	m.scale_min = _k(kind, "scale", 0.07) * 0.6 * z
	m.scale_max = _k(kind, "scale", 0.07) * z
	m.gravity = Vector3(0, -_k(kind, "gravity", 12.0) * z, 0)
	m.color = color
	var mat: StandardMaterial3D = p.draw_pass_1.surface_get_material(0)
	mat.albedo_color = color
	p.amount = max(2, int(_k(kind, "amount", 12.0) * pw))
	p.restart()
	p.emitting = true
	add_shake(_k(kind, "shake", 0.0) * pw)

func add_shake(amount: float) -> void:
	shake = min(_shake_max, shake + amount)

## 相机每帧问一次要偏多少。抖动是纯表现，不进模拟。
func shake_offset() -> Vector3:
	if shake <= 0.001:
		return Vector3.ZERO
	return Vector3(sin(_t * _shake_freq) * shake,
		sin(_t * _shake_freq * 1.37 + 1.1) * shake * 0.7, 0.0)

func _process(delta: float) -> void:
	_t += delta
	if shake > 0.0:
		shake = max(0.0, shake - _shake_decay * delta * max(shake, 0.25))
