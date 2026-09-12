class_name Trap
extends Node3D
## 机关实例。效果按 触发/目标/伤害/冲击位移/状态 五段组件组装（文档 15.3）

var id: String = ""
var data: Dictionary = {}
var cell: Vector2i = Vector2i.ZERO
var facing: Vector2i = Vector2i(0, 1)
var mount: String = "ground"
var coverage: Array[Vector2i] = []
var trigger_state: Dictionary = {"cooldown_left": 0.0}
var game = null

var view: TrapView = null
var _mat: StandardMaterial3D = null
var _base_color: Color = Color.WHITE
var _flash: float = 0.0

func setup(p_id: String, p_data: Dictionary, p_cell: Vector2i, p_facing: Vector2i, p_game) -> void:
	id = p_id
	data = p_data
	cell = p_cell
	facing = p_facing
	mount = String(data.get("mount", "ground"))
	game = p_game
	_base_color = Cfg.to_color(data.get("color"), Color(0.8, 0.8, 0.8))
	coverage = TrapTargeting.compute(data.get("targeting", {}), cell, facing, game.grid)
	_build_view()

func source_id() -> String:
	return "trap:" + id

func display_name() -> String:
	return String(data.get("name", id))

func cost() -> int:
	return int(Cfg.dget(data, "cost", 0.0))

func cooldown_ratio() -> float:
	var cd := float(data.get("trigger", {}).get("cooldown", 0.0))
	if cd <= 0.0:
		return 0.0
	return clampf(float(trigger_state.get("cooldown_left", 0.0)) / cd, 0.0, 1.0)

# ---------------------------------------------------------------- 推进

func step(dt: float) -> void:
	trigger_state["cooldown_left"] = max(0.0, float(trigger_state.get("cooldown_left", 0.0)) - dt)
	_flash = max(0.0, _flash - dt * 4.0)
	_refresh_tint()

	var enemies: Array = game.enemies_in_cells(coverage)
	if not TrapTrigger.evaluate(data.get("trigger", {}), trigger_state, enemies, dt):
		return

	var src := source_id()
	var payload: Dictionary = data.get("payload", {})
	var disp: Dictionary = data.get("displacement", {})
	var status: Dictionary = data.get("status", {})
	for e in enemies:
		if e.state == Enemy.State.DEAD:
			continue
		var dealt := TrapPayload.apply(payload, e, dt, src)
		if dealt > 0.0:
			game.stats.add_damage(src, dealt)
		TrapDisplacement.apply(disp, e, facing, src)
		TrapStatus.apply(status, e, src)
	if not status.is_empty() and not enemies.is_empty():
		game.stats.add_control(src, dt * float(enemies.size()))
	_flash = 1.0
	if view != null:
		view.fire()

# ---------------------------------------------------------------- 表现

func _build_view() -> void:
	var cs: float = game.grid.cell_size
	var model_id := TrapView.model_for(data)
	if model_id != "":
		var v := TrapView.new()
		add_child(v)
		if v.setup(model_id, cs, _base_color, data.get("anim", {})):
			view = v
			if mount == "ground":
				if bool(data.get("directional", false)):
					v.rotation.y = atan2(-float(facing.x), -float(facing.y))
			else:
				# 墙面机关：原点挪到墙面上，模型自己往朝向伸出
				v.position = Vector3(float(facing.x), 0.0, float(facing.y)) * (cs * 0.5)
				v.rotation.y = atan2(-float(facing.x), -float(facing.y))
			return
		v.queue_free()
	var mesh := MeshInstance3D.new()
	var box := BoxMesh.new()
	_mat = StandardMaterial3D.new()
	_mat.albedo_color = _base_color
	mesh.material_override = _mat

	if mount == "ground":
		box.size = Vector3(cs * 0.8, 0.18, cs * 0.8)
		mesh.position = Vector3(0, 0.09, 0)
	else:
		# 贴在墙的暴露面上
		box.size = Vector3(cs * 0.7, game.wall_height * 0.6, 0.22)
		mesh.position = Vector3(0, game.wall_height * 0.6, 0)
		mesh.rotation.y = atan2(float(facing.x), float(facing.y))
		mesh.position += Vector3(float(facing.x), 0.0, float(facing.y)) * (cs * 0.5)
	mesh.mesh = box
	add_child(mesh)

	if bool(data.get("directional", false)):
		add_child(_make_arrow(cs))

func _make_arrow(cs: float) -> MeshInstance3D:
	var arrow := MeshInstance3D.new()
	var prism := PrismMesh.new()
	prism.size = Vector3(cs * 0.3, cs * 0.35, 0.12)
	arrow.mesh = prism
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(1, 1, 1, 0.9)
	m.emission_enabled = true
	m.emission = Color(1, 1, 1)
	m.emission_energy_multiplier = 0.6
	arrow.material_override = m
	arrow.rotation = Vector3(-PI * 0.5, atan2(float(facing.x), float(facing.y)), 0)
	var lift: float = 0.25 if mount == "ground" else game.wall_height * 0.9
	arrow.position = Vector3(float(facing.x), 0.0, float(facing.y)) * (cs * 0.45) + Vector3(0, lift, 0)
	return arrow

func _refresh_tint() -> void:
	var cd := cooldown_ratio()
	if view != null:
		if view.keeps_own_color:
			view.set_dim(cd * 0.55)          # 面板：等级色是模型自带的，只压暗
		else:
			view.set_color(_base_color.lerp(Color(0.30, 0.30, 0.33), cd * 0.55))
		return
	if _mat == null:
		return
	var c: Color = _base_color.lerp(Color(0.16, 0.16, 0.18), cd * 0.75)
	if _flash > 0.0:
		c = c.lerp(Color(1, 1, 1), _flash * 0.8)
	_mat.albedo_color = c
