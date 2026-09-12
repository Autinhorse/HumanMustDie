class_name Enemy
extends Node3D
## 敌人：位移完全由游戏逻辑驱动（不用刚体），保证同种子可复现（文档 15.3）

enum State { GROUND, THROWN, FALLING, DEAD }

static var _next_uid := 0

var uid: int = 0
var type_id: String = ""
var data: Dictionary = {}
var game = null            # Game
var grid: HGrid = null

var hp: float = 1.0
var max_hp: float = 1.0
var speed: float = 3.0
var mass: float = 1.0
var stability: float = 0.0
var impact: float = 0.0
var impact_decay: float = 1.0
var radius: float = 0.4
var height: float = 1.2
var core_damage: int = 1
var gold: int = 1

var state: int = State.GROUND
var vel: Vector3 = Vector3.ZERO
var slow_factor: float = 1.0
var slow_until: float = -1.0
var wander: Vector3 = Vector3.ZERO      # 每个敌人在格内的固定偏移，避免完全重叠
var last_impulse_by: String = ""
var last_impulse_time: float = -999.0
var last_collide_time: float = -999.0
var recent_sources: Dictionary = {}     # source -> 最后一次接触时间，用于 Combo 归属
var dead_cause: String = ""
var dead_source: String = ""

var actor: ActorView = null
var run_phase: float = 0.0
var _landed: bool = false
var _mesh: MeshInstance3D = null
var _mat: StandardMaterial3D = null
var _base_color: Color = Color.WHITE

func setup(p_type: String, p_data: Dictionary, p_game) -> void:
	_next_uid += 1
	uid = _next_uid
	type_id = p_type
	data = p_data
	game = p_game
	grid = p_game.grid
	max_hp = Cfg.dget(data, "hp", 40.0)
	hp = max_hp
	speed = Cfg.dget(data, "speed", 3.0)
	mass = max(Cfg.dget(data, "mass", 1.0), 0.01)
	stability = Cfg.dget(data, "stability", 0.0)
	impact_decay = Cfg.dget(data, "impact_decay", 1.0)
	radius = Cfg.dget(data, "radius", 0.4)
	height = Cfg.dget(data, "height", 1.2)
	core_damage = int(Cfg.dget(data, "core_damage", 1.0))
	gold = int(Cfg.dget(data, "gold", 1.0))
	_base_color = Cfg.to_color(data.get("color"), Color(0.8, 0.8, 0.8))
	_build_view()

func _build_view() -> void:
	var model_id := String(data.get("model", ""))
	if model_id != "":
		var a := ActorView.new()
		add_child(a)
		if a.setup(model_id, height, _base_color):
			actor = a
			return
		a.queue_free()
	_mesh = MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.radius = radius
	capsule.height = max(height, radius * 2.0 + 0.05)
	_mesh.mesh = capsule
	_mat = StandardMaterial3D.new()
	_mat.albedo_color = _base_color
	_mesh.material_override = _mat
	_mesh.position = Vector3(0, capsule.height * 0.5, 0)
	add_child(_mesh)

func display_name() -> String:
	return String(data.get("name", type_id))

func class_name_cn() -> String:
	return String(data.get("class", "?"))

# ---------------------------------------------------------------- 状态与受击

func touch(source: String) -> void:
	if source != "":
		recent_sources[source] = game.sim_time

func take_damage(amount: float, source: String, cause: String = "kill") -> float:
	if state == State.DEAD or amount <= 0.0:
		return 0.0
	var dealt: float = min(amount, hp)
	hp -= dealt
	touch(source)
	_refresh_tint()
	if hp <= 0.0:
		die(cause, source)
	else:
		var f: float = clampf(dealt / max(max_hp * 0.35, 0.001), 0.2, 1.0)
		game.fx("hit", position + Vector3(0, height * 0.55, 0), Vector3.ZERO,
			game.source_color(source), f)
	return dealt

func apply_slow(factor: float, duration: float, source: String) -> void:
	if state == State.DEAD:
		return
	slow_factor = min(slow_factor, clampf(factor, 0.05, 1.0))
	slow_until = game.sim_time + duration
	touch(source)
	_refresh_tint()

## 冲击进积累槽；超过稳定值才发生位移。小型 stability=0 → 每次都被击飞。
func apply_impulse(dir: Vector3, force: float, up: float, source: String) -> void:
	if state == State.DEAD or force <= 0.0:
		return
	touch(source)
	impact += force
	last_impulse_by = source
	if impact + 0.0001 < stability:
		return
	var v: float = (impact / mass) * game.c_impulse_to_velocity
	impact = 0.0
	var d := dir
	d.y = 0.0
	if d.length() < 0.001:
		d = Vector3(0, 0, 1)
	d = d.normalized()
	vel = d * v
	vel.y = max(up * v, game.c_min_launch_up)
	state = State.THROWN
	_landed = false
	last_impulse_time = game.sim_time
	game.stats.add_displacement(source)
	game.fx("launch", position + Vector3(0, height * 0.3, 0), vel.normalized(),
		game.source_color(source), clampf(v / 14.0, 0.3, 1.0))
	game.add_hitstop(Cfg.dget(Cfg.art.get("fx", {}).get("launch", {}), "hitstop", 0.0))

func die(cause: String, source: String) -> void:
	if state == State.DEAD:
		return
	state = State.DEAD
	dead_cause = cause
	dead_source = source
	game.fx("death", position + Vector3(0, height * 0.5, 0), Vector3.ZERO, _base_color, 1.0)
	game.add_hitstop(Cfg.dget(Cfg.art.get("fx", {}).get("death", {}), "hitstop", 0.0))

# ---------------------------------------------------------------- 每步推进

func step(dt: float) -> void:
	if state == State.DEAD:
		return
	if impact > 0.0:
		impact = max(0.0, impact - impact_decay * dt)
	if game.sim_time > slow_until and slow_factor < 1.0:
		slow_factor = 1.0
		_refresh_tint()
	var prev_pos := position
	match state:
		State.GROUND:
			_step_ground(dt)
		State.THROWN:
			_step_thrown(dt)
		State.FALLING:
			_step_falling(dt)
	_animate(prev_pos, dt)

## 动作由移动距离驱动，倍速播放时步频自然跟着变
func _animate(prev_pos: Vector3, dt: float) -> void:
	if actor == null:
		return
	actor.apply_view(game.view_unit_scale, game.view_marker)
	var delta := position - prev_pos
	delta.y = 0.0
	var dist := delta.length()
	if dist > 0.0005:
		actor.rotation.y = atan2(-delta.x, -delta.z)
	if state == State.GROUND:
		# 步幅越大，一个跑步循环走过的距离越长、耗时也越长
		var ratio: float = float(Cfg.art.get("anim", {}).get("stride_ratio", 0.715))
		var stride: float = max(height * ratio, 0.2)
		run_phase += dist / stride * PI
		var intensity: float = clampf(dist / max(speed * dt, 0.0001), 0.0, 1.0)
		actor.set_run(run_phase, intensity)
	else:
		actor.set_tumble(game.sim_time)

func _step_ground(dt: float) -> void:
	var cell := grid.world_to_cell(position)
	if grid.get_cell(cell) == HGrid.Cell.CORE:
		game.on_enemy_reached_core(self)
		return
	if not grid.is_walkable(cell):
		# 落点异常：拉回最近的可行走格
		var fix: Vector2i = game.nearest_walkable(cell)
		if fix != cell:
			position = grid.cell_center(fix)
		return
	var next: Vector2i = game.flow.next_cell(cell)
	var target: Vector3 = grid.cell_center(next)
	if next != cell:
		target += wander
	var to := target - position
	to.y = 0.0
	var dist := to.length()
	var move := speed * slow_factor * dt
	if dist <= move or dist < 0.001:
		position = Vector3(target.x, 0.0, target.z)
	else:
		position += to / dist * move
	position.y = 0.0

func _step_thrown(dt: float) -> void:
	var prev := position
	if position.y > 0.0 or vel.y > 0.0:
		vel.y -= game.c_gravity * dt
	position += vel * dt

	# 撞墙/撞障碍：低于墙高时被挡住，水平速度反弹衰减
	var cell := grid.world_to_cell(position)
	var t := grid.get_cell(cell)
	if (t == HGrid.Cell.WALL or t == HGrid.Cell.OBSTACLE) and position.y < game.wall_height:
		position = prev
		vel.x *= -0.35
		vel.z *= -0.35

	if position.y > 0.0:
		return

	var c := grid.world_to_cell(position)
	if grid.is_wall(c) or grid.get_cell(c) == HGrid.Cell.OBSTACLE:
		position = prev
		position.y = 0.0
		vel = Vector3.ZERO
		state = State.GROUND
		_landed = false
		return
	if not grid.is_walkable(c):
		# 空地：下面是镂空的，开始坠落
		state = State.FALLING
		game.stats.add_fall_entered()
		game.fx("fall", position, Vector3.DOWN, game.dust_color, 1.0)
		return

	# 落到地面：先结算落地伤害，然后带摩擦滑行（滑行途中依然可能滑出边缘掉下去）
	position.y = 0.0
	vel.y = 0.0
	if not _landed:
		_landed = true
		var land_speed := speed_h()
		game.fx("land", position, Vector3.ZERO, game.dust_color,
			clampf(land_speed / 12.0, 0.2, 1.0))
		if land_speed > game.c_landing_speed_threshold:
			var dmg: float = (land_speed - game.c_landing_speed_threshold) * mass * game.c_landing_damage_coef
			take_damage(dmg, last_impulse_by if last_impulse_by != "" else "impact")
	var h := Vector2(vel.x, vel.z)
	var sp: float = max(0.0, h.length() - game.c_friction * dt)
	if sp < 0.35:
		vel = Vector3.ZERO
		state = State.GROUND
		_landed = false
	else:
		h = h.normalized() * sp
		vel.x = h.x
		vel.z = h.y

func _step_falling(dt: float) -> void:
	vel.y -= game.c_gravity * dt
	position += vel * dt
	if position.y < game.c_fall_kill_y:
		die("fall", last_impulse_by if last_impulse_by != "" else "fall")

# ---------------------------------------------------------------- 表现

func _refresh_tint() -> void:
	if actor != null:
		actor.set_state_tint(hp / max_hp, slow_factor < 1.0)
		return
	if _mat == null:
		return
	var ratio := clampf(hp / max_hp, 0.0, 1.0)
	var c: Color = _base_color.lerp(Color(0.35, 0.05, 0.05), 1.0 - ratio)
	if slow_factor < 1.0:
		c = c.lerp(Color(0.3, 0.6, 1.0), 0.35)
	_mat.albedo_color = c

func speed_h() -> float:
	return Vector2(vel.x, vel.z).length()

func status_text() -> String:
	var parts: Array[String] = []
	parts.append("%s(%s)" % [display_name(), class_name_cn()])
	parts.append("HP %d/%d" % [int(ceil(hp)), int(max_hp)])
	parts.append("质量 %.1f" % mass)
	parts.append("稳定 %.0f" % stability)
	parts.append("冲击 %.1f" % impact)
	if slow_factor < 1.0:
		parts.append("减速 %d%%" % int((1.0 - slow_factor) * 100.0))
	match state:
		State.THROWN:
			parts.append("被击飞")
		State.FALLING:
			parts.append("坠落中")
	return "  ".join(parts)
