class_name Game
extends Node3D
## 模拟核心：固定步长推进，所有随机走同一个种子，保证同一局可复现（文档 15.3）

signal changed
signal logged(line: String)

enum Phase { BUILD, COMBAT, WIN, LOSE }

const PHASE_NAMES := {Phase.BUILD: "建造", Phase.COMBAT: "战斗", Phase.WIN: "胜利", Phase.LOSE: "失败"}

var grid: HGrid = null
var flow: FlowField = null
var level: Dictionary = {}
var level_id: String = "corridor_01"
var entrance_cells: Array[Vector2i] = []
var core_cells: Array[Vector2i] = []
var load_error: String = ""

var enemies: Array = []
var traps: Array = []
var _trap_index: Dictionary = {}
var _enemy_by_cell: Dictionary = {}

var phase: int = Phase.BUILD
var wave_index: int = -1
var gold: int = 0
var core_hp: int = 20
var sandbox: bool = false
var paused: bool = false
var sim_speed: float = 1.0
var speed_index: int = 1
var sim_time: float = 0.0

## 表现层事件队列。模拟只管往里塞，main.gd 每帧取走交给 Fx。
## 这样加特效不会动到定点步进的结果，无头测试也不用建粒子。
var fx_queue: Array[Dictionary] = []
## 命中顿帧：只影响 _process 的推进节奏，step_sim 本身不受影响
var hitstop: float = 0.0

func fx(kind: String, pos: Vector3, dir: Vector3, color: Color, power: float) -> void:
	if fx_queue.size() >= 192:        # 一波怪同时死的时候别把内存吃穿
		return
	fx_queue.append({"kind": kind, "pos": pos, "dir": dir, "color": color, "power": power})

func add_hitstop(seconds: float) -> void:
	hitstop = max(hitstop, seconds)

## 火花用打中它的那个机关的颜色 —— 一眼看出这一下是谁打的，
## 连锁击杀的时候尤其重要（文档 §19 的卖点就是连锁）。
## 当前放着的机关。表现层要按机关决定地块怎么画（比如尖刺板要挖掉地板）。
func trap_list() -> Array:
	return _trap_root.get_children() if _trap_root != null else []

func source_color(source: String) -> Color:
	var d: Dictionary = Cfg.traps.get(source, {})
	if d.is_empty():
		return Color(0.95, 0.86, 0.62)      # 撞击、坠落这类没有机关来源
	return Cfg.to_color(d.get("color"), Color(0.95, 0.86, 0.62))

var dust_color: Color:
	get:
		return Cfg.to_color(Cfg.art.get("fx", {}).get("dust_color"), Color(0.82, 0.79, 0.72))
# 由 main.gd 随相机缩放更新：单位放大倍率、地面标记强度（0~1）
var view_unit_scale: float = 1.0
var view_marker: float = 0.0
var wave_elapsed: float = 0.0
var rng := RandomNumberGenerator.new()
var stats := RunStats.new()
var seed_value: int = 0

# 缓存的配置数值（每步都要用，避免反复查字典）
var wall_height := 1.0
var c_gravity := 24.0
var c_friction := 7.0
var c_impulse_to_velocity := 0.6
var c_min_launch_up := 0.25
var c_fall_kill_y := -8.0
var c_collision_speed := 2.5
var c_collision_damage := 2.2
var c_collision_transfer := 0.45
var c_collision_cooldown := 0.35
var c_landing_speed_threshold := 7.0
var c_landing_damage_coef := 1.2
var c_combo_window := 2.0
var c_separation := 0.55

var _spawn_queue: Array = []
var _acc := 0.0
var _step := 1.0 / 60.0
var _max_steps := 40

var _corpses: Array = []
var _enemy_root: Node3D = null
var _trap_root: Node3D = null

# ---------------------------------------------------------------- 生命周期

func start(p_level_id: String) -> void:
	level_id = p_level_id
	reset()

func reset() -> void:
	load_error = ""
	_cache_config()
	for c in get_children():
		remove_child(c)
		c.queue_free()
	enemies.clear()
	_corpses.clear()
	traps.clear()
	_trap_index.clear()
	_enemy_by_cell.clear()
	_enemy_root = Node3D.new()
	_enemy_root.name = "Enemies"
	add_child(_enemy_root)
	_trap_root = Node3D.new()
	_trap_root.name = "Traps"
	add_child(_trap_root)

	level = Cfg.levels.get(level_id, {})
	if level.is_empty():
		load_error = "找不到关卡数据: %s" % level_id
		return
	grid = HGrid.new()
	var err := grid.load_rows(level.get("grid", []), Cfg.num("grid.cell_size", 2.0))
	if err != "":
		load_error = "关卡 %s 网格错误: %s" % [level_id, err]
		return

	core_cells = grid.cells_of_type(HGrid.Cell.CORE)
	if core_cells.is_empty():
		load_error = "关卡缺少目标核心（格子类型 5）"
		return
	flow = FlowField.new()
	flow.build(grid, core_cells)
	entrance_cells = _resolve_entrance()
	if entrance_cells.is_empty():
		load_error = "找不到入口：地图边缘没有可通往核心的地面/桥面，关卡里也没有写 entrance"
		return

	seed_value = Cfg.int_at("sim.seed", 12345)
	rng.seed = seed_value
	gold = Cfg.int_at("economy.start_gold", 300)
	core_hp = Cfg.int_at("economy.core_hp", 20)
	phase = Phase.BUILD
	wave_index = -1
	sim_time = 0.0
	wave_elapsed = 0.0
	sandbox = false
	_spawn_queue.clear()
	stats = RunStats.new()
	var how: String = "关卡指定" if level.has("entrance") else "自动推导"
	_log("关卡「%s」载入完成，入口 %d 格（%s），随机种子 %d" % [
		String(level.get("name", level_id)), entrance_cells.size(), how, seed_value])
	changed.emit()

## 入口：关卡里写了 entrance 就用写的，没写就按规则自动推
## （地图边缘上离核心最远的那个连通开口）。
## entrance 支持 "x,y" 和 "x,y-x,y" 两种写法，可以列多段 —— 多段就是多个入口。
func _resolve_entrance() -> Array[Vector2i]:
	var spec: Variant = level.get("entrance", null)
	if spec != null:
		var listed := _parse_cells(spec)
		var good: Array[Vector2i] = []
		var bad: Array[String] = []
		for c in listed:
			if not grid.is_walkable(c):
				bad.append("%s 不是地面/桥面" % str(c))
			elif not flow.reachable(c):
				bad.append("%s 走不到核心" % str(c))
			else:
				good.append(c)
		for b in bad:
			_log("关卡 entrance 里的 %s，已忽略" % b)
		if not good.is_empty():
			return good
		_log("关卡 entrance 一个可用的都没有，改用自动推导")
	return flow.find_entrance_cells()

## 解析 "x,y" / "x,y-x,y" / [x,y]，返回展开后的格子
func _parse_cells(spec: Variant) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	var items: Array = spec if typeof(spec) == TYPE_ARRAY else [spec]
	for item in items:
		if typeof(item) == TYPE_ARRAY and item.size() >= 2:
			out.append(Vector2i(int(item[0]), int(item[1])))
			continue
		var text := String(item).strip_edges()
		if text == "":
			continue
		var ends := text.split("-")
		var a := _parse_one(ends[0])
		var b := _parse_one(ends[1]) if ends.size() > 1 else a
		for y in range(min(a.y, b.y), max(a.y, b.y) + 1):
			for x in range(min(a.x, b.x), max(a.x, b.x) + 1):
				out.append(Vector2i(x, y))
	return out

func _parse_one(text: String) -> Vector2i:
	var parts := text.strip_edges().split(",")
	if parts.size() < 2:
		return Vector2i(-1, -1)
	return Vector2i(int(parts[0].strip_edges()), int(parts[1].strip_edges()))

func _cache_config() -> void:
	wall_height = Cfg.num("grid.wall_height", 1.0)
	c_gravity = Cfg.num("combat.gravity", 24.0)
	c_friction = Cfg.num("combat.ground_friction", 7.0)
	c_impulse_to_velocity = Cfg.num("combat.impulse_to_velocity", 0.6)
	c_min_launch_up = Cfg.num("combat.min_launch_up", 0.25)
	c_fall_kill_y = Cfg.num("combat.fall_kill_y", -8.0)
	c_collision_speed = Cfg.num("combat.collision_speed_threshold", 2.5)
	c_collision_damage = Cfg.num("combat.collision_damage_coef", 2.2)
	c_collision_transfer = Cfg.num("combat.collision_impulse_transfer", 0.45)
	c_collision_cooldown = Cfg.num("combat.collision_cooldown", 0.35)
	c_landing_speed_threshold = Cfg.num("combat.landing_speed_threshold", 7.0)
	c_landing_damage_coef = Cfg.num("combat.landing_damage_coef", 1.2)
	c_combo_window = Cfg.num("combat.combo_window", 2.0)
	c_separation = Cfg.num("combat.enemy_separation", 0.55)
	_step = max(Cfg.num("sim.step", 1.0 / 60.0), 0.004)
	_max_steps = Cfg.int_at("sim.max_steps_per_frame", 40)
	var speeds := Cfg.arr("sim.speeds", [0.5, 1.0, 2.0, 4.0])
	speed_index = clampi(Cfg.int_at("sim.default_speed_index", 1), 0, speeds.size() - 1)
	sim_speed = float(speeds[speed_index])

func _process(delta: float) -> void:
	if load_error != "":
		return
	if paused:
		return
	if phase == Phase.BUILD:
		stats.prep_timer += delta
		return
	if phase != Phase.COMBAT:
		return
	if hitstop > 0.0:
		# 顿帧：画面还在跑（粒子、抖动照常），只是模拟停一下，打击才有"咬合感"
		hitstop -= delta
		return
	_acc += delta * sim_speed
	var steps := 0
	while _acc >= _step and steps < _max_steps:
		_acc -= _step
		steps += 1
		_step_sim(_step)
		if phase != Phase.COMBAT:
			break

# ---------------------------------------------------------------- 单步推进

func _step_sim(dt: float) -> void:
	sim_time += dt
	wave_elapsed += dt
	stats.combat_timer += dt
	_spawn_due()
	_rebuild_enemy_cells()
	for t in traps:
		t.step(dt)
	for e in enemies:
		e.step(dt)
	_resolve_contacts(dt)
	_cleanup()
	_step_corpses(dt)
	if _spawn_queue.is_empty() and enemies.is_empty() and phase == Phase.COMBAT:
		_finish_wave()

func _rebuild_enemy_cells() -> void:
	_enemy_by_cell.clear()
	for e in enemies:
		if e.state == Enemy.State.DEAD:
			continue
		var c := grid.world_to_cell(e.position)
		if not _enemy_by_cell.has(c):
			_enemy_by_cell[c] = []
		_enemy_by_cell[c].append(e)

func enemies_in_cells(cells: Array) -> Array:
	var out: Array = []
	for c in cells:
		if _enemy_by_cell.has(c):
			for e in _enemy_by_cell[c]:
				out.append(e)
	return out

## 拥挤分离 + 被击飞单位撞击沿途敌人（文档 8：重型只短移，但可撞伤小怪）
func _resolve_contacts(_dt: float) -> void:
	var n := enemies.size()
	for i in range(n):
		var a = enemies[i]
		if a.state == Enemy.State.DEAD:
			continue
		for j in range(i + 1, n):
			var b = enemies[j]
			if b.state == Enemy.State.DEAD:
				continue
			var d: Vector3 = b.position - a.position
			d.y = 0.0
			var min_d: float = a.radius + b.radius
			var dist := d.length()
			if dist >= min_d or dist < 0.0001:
				continue
			var flying_a: bool = a.state == Enemy.State.THROWN and a.speed_h() > c_collision_speed
			var flying_b: bool = b.state == Enemy.State.THROWN and b.speed_h() > c_collision_speed
			if flying_a or flying_b:
				var hitter = a if flying_a else b
				var victim = b if flying_a else a
				if sim_time - victim.last_collide_time < c_collision_cooldown:
					continue
				victim.last_collide_time = sim_time
				var sp: float = hitter.speed_h()
				var dmg: float = sp * hitter.mass * c_collision_damage
				var src: String = hitter.last_impulse_by if hitter.last_impulse_by != "" else "collision"
				var dealt: float = victim.take_damage(dmg, src, "collision")
				stats.add_damage(src, dealt)
				var push: Vector3 = victim.position - hitter.position
				push.y = 0.0
				victim.apply_impulse(push, sp * hitter.mass * c_collision_transfer, 0.1, src)
				hitter.vel *= 0.65
			else:
				var push_dir: Vector3 = d / dist
				var overlap: float = (min_d - dist) * 0.5 * c_separation
				if a.state == Enemy.State.GROUND:
					a.position -= push_dir * overlap
				if b.state == Enemy.State.GROUND:
					b.position += push_dir * overlap

## 尸体不再参与模拟，只把倒地动画放完
func _step_corpses(dt: float) -> void:
	if _corpses.is_empty():
		return
	var anim := Cfg.num("combat.death_anim_time", 0.55)
	var life := Cfg.num("combat.corpse_life", 3.0)
	var keep: Array = []
	for c in _corpses:
		var e = c["node"]
		if not is_instance_valid(e):
			continue
		c["t"] = float(c["t"]) + dt
		var t: float = c["t"]
		e.actor.set_death(clampf(t / anim, 0.0, 1.0))
		e.actor.step_sword(dt, c_gravity)
		if t < life:
			keep.append(c)
		else:
			e.queue_free()
	_corpses = keep

func _cleanup() -> void:
	var alive: Array = []
	for e in enemies:
		if e.state != Enemy.State.DEAD:
			alive.append(e)
			continue
		_on_enemy_died(e)
		# 掉下地图和抵达核心的不留尸体；其余播完倒地动画再清掉
		if e.actor != null and e.dead_cause != "fall" and e.dead_cause != "core":
			_corpses.append({"node": e, "t": 0.0})
		else:
			e.queue_free()
	enemies = alive

func _on_enemy_died(e) -> void:
	var combo := 0
	for src in e.recent_sources.keys():
		if sim_time - float(e.recent_sources[src]) <= c_combo_window:
			combo += 1
	if e.dead_cause != "core":
		stats.add_kill(e.dead_cause, e.dead_source, combo >= 2)
		gold += e.gold
	if Cfg.num("debug.log_kills", 1.0) > 0.0 and e.dead_cause != "core":
		var by: String = e.dead_source.replace("trap:", "")
		var by_name: String = String(Cfg.traps.get(by, {}).get("name", by))
		var cause_cn: String = String({"kill": "击杀", "fall": "坠落处决", "collision": "撞击"}.get(e.dead_cause, e.dead_cause))
		var combo_tag: String = "（连锁）" if combo >= 2 else ""
		_log("[%.1fs] %s 被 %s %s%s" % [sim_time, e.display_name(), by_name, cause_cn, combo_tag])
	changed.emit()

func on_enemy_reached_core(e) -> void:
	core_hp -= e.core_damage
	stats.add_leak()
	_log("[%.1fs] %s 抵达核心，核心生命 -%d" % [sim_time, e.display_name(), e.core_damage])
	e.die("core", "core")
	if core_hp <= 0:
		core_hp = 0
		phase = Phase.LOSE
		_log("核心被摧毁，本局失败。")
	changed.emit()

func nearest_walkable(c: Vector2i) -> Vector2i:
	if grid.is_walkable(c):
		return c
	for r in range(1, 5):
		for dy in range(-r, r + 1):
			for dx in range(-r, r + 1):
				var n := c + Vector2i(dx, dy)
				if grid.is_walkable(n):
					return n
	return c

# ---------------------------------------------------------------- 波次

func wave_count() -> int:
	return level.get("waves", []).size()

func current_wave_name() -> String:
	var waves: Array = level.get("waves", [])
	if wave_index < 0 or wave_index >= waves.size():
		return "-"
	return String(waves[wave_index].get("name", "第%d波" % (wave_index + 1)))

func next_wave_summary() -> String:
	var waves: Array = level.get("waves", [])
	var i := wave_index + 1
	if i >= waves.size():
		return "已是最后一波"
	var counts := {}
	for g in waves[i].get("groups", []):
		var id := String(g.get("enemy", ""))
		counts[id] = int(counts.get(id, 0)) + int(g.get("count", 0))
	var parts: Array[String] = []
	for id in counts.keys():
		parts.append("%s x%d" % [String(Cfg.enemies.get(id, {}).get("name", id)), int(counts[id])])
	return "%s：%s" % [String(waves[i].get("name", "第%d波" % (i + 1))), "  ".join(parts)]

func start_wave() -> bool:
	if phase != Phase.BUILD:
		return false
	var waves: Array = level.get("waves", [])
	if wave_index + 1 >= waves.size():
		return false
	wave_index += 1
	wave_elapsed = 0.0
	_acc = 0.0
	_spawn_queue.clear()
	for g in waves[wave_index].get("groups", []):
		var id := String(g.get("enemy", ""))
		var count := int(g.get("count", 0))
		var interval := float(g.get("interval", 0.5))
		var delay := float(g.get("delay", 0.0))
		for i in count:
			_spawn_queue.append({"t": delay + float(i) * interval, "id": id})
	_spawn_queue.sort_custom(_cmp_spawn)
	phase = Phase.COMBAT
	_log("=== %s 开始 ===" % current_wave_name())
	changed.emit()
	return true

func _cmp_spawn(a: Dictionary, b: Dictionary) -> bool:
	return float(a["t"]) < float(b["t"])

func _spawn_due() -> void:
	while not _spawn_queue.is_empty() and float(_spawn_queue[0]["t"]) <= wave_elapsed:
		var item: Dictionary = _spawn_queue.pop_front()
		spawn(String(item["id"]))

func spawn(enemy_id: String) -> void:
	var data: Dictionary = Cfg.enemies.get(enemy_id, {})
	if data.is_empty():
		_log("未知敌人类型: %s" % enemy_id)
		return
	if entrance_cells.is_empty():
		return
	var cell: Vector2i = entrance_cells[rng.randi_range(0, entrance_cells.size() - 1)]
	spawn_at(enemy_id, cell)

## 在指定格子生成敌人（沙盒与自动化测试用）
func spawn_at(enemy_id: String, cell: Vector2i) -> Enemy:
	var data: Dictionary = Cfg.enemies.get(enemy_id, {})
	if data.is_empty():
		return null
	var e := Enemy.new()
	e.setup(enemy_id, data, self)
	var jitter: float = grid.cell_size * 0.22
	e.wander = Vector3(rng.randf_range(-jitter, jitter), 0.0, rng.randf_range(-jitter, jitter))
	e.position = grid.cell_center(cell) + e.wander
	_enemy_root.add_child(e)
	enemies.append(e)
	return e

## 供测试/工具直接推进一个固定步
func step_sim(dt: float) -> void:
	_step_sim(dt)

func _finish_wave() -> void:
	stats.close_wave(wave_index)
	var reward := Cfg.int_at("economy.wave_clear_gold", 60)
	gold += reward
	_log("=== %s 结束，奖励 %d 金币 ===" % [current_wave_name(), reward])
	if wave_index + 1 >= wave_count():
		phase = Phase.WIN
		_log("全部波次守住，本局胜利。")
	else:
		phase = Phase.BUILD
	changed.emit()

# ---------------------------------------------------------------- 机关放置

func trap_key(cell: Vector2i, facing: Vector2i, mount: String) -> String:
	if mount == "ground":
		return "g:%d,%d" % [cell.x, cell.y]
	return "w:%d,%d,%d,%d" % [cell.x, cell.y, facing.x, facing.y]

func can_place(trap_id: String, cell: Vector2i, facing: Vector2i) -> Dictionary:
	var data: Dictionary = Cfg.traps.get(trap_id, {})
	if data.is_empty():
		return {"ok": false, "reason": "未知机关"}
	if phase == Phase.COMBAT and not sandbox:
		return {"ok": false, "reason": "战斗阶段不能施工"}
	var mount := String(data.get("mount", "ground"))
	if mount == "ground":
		var t := grid.get_cell(cell)
		if t != HGrid.Cell.FLOOR and t != HGrid.Cell.BRIDGE:
			return {"ok": false, "reason": "地面机关只能放在地面或桥面"}
	else:
		if not grid.is_wall(cell):
			return {"ok": false, "reason": "墙面机关只能放在墙上"}
		if not grid.wall_face_free(cell, facing):
			return {"ok": false, "reason": "这一面被另一面墙挡住"}
	if _trap_index.has(trap_key(cell, facing, mount)):
		return {"ok": false, "reason": "这个位置已有机关"}
	if not sandbox and gold < int(Cfg.dget(data, "cost", 0.0)):
		return {"ok": false, "reason": "金币不足"}
	return {"ok": true, "reason": ""}

func place(trap_id: String, cell: Vector2i, facing: Vector2i) -> bool:
	var check := can_place(trap_id, cell, facing)
	if not bool(check["ok"]):
		return false
	var data: Dictionary = Cfg.traps[trap_id]
	var t := Trap.new()
	t.setup(trap_id, data, cell, facing, self)
	t.position = grid.cell_center(cell)
	_trap_root.add_child(t)
	traps.append(t)
	_trap_index[trap_key(cell, facing, t.mount)] = t
	if not sandbox:
		gold -= t.cost()
	_log("放置 %s @ (%d,%d)" % [t.display_name(), cell.x, cell.y])
	changed.emit()
	return true

func trap_at_cell(cell: Vector2i) -> Trap:
	for t in traps:
		if t.cell == cell:
			return t
	return null

func sell(t: Trap) -> void:
	if t == null:
		return
	if phase == Phase.COMBAT and not sandbox:
		return
	var refund := int(float(t.cost()) * Cfg.num("economy.sell_refund", 0.6))
	if not sandbox:
		gold += refund
	_trap_index.erase(trap_key(t.cell, t.facing, t.mount))
	traps.erase(t)
	t.queue_free()
	_log("拆除 %s，返还 %d 金币" % [t.display_name(), refund])
	changed.emit()

# ---------------------------------------------------------------- 杂项

func allowed_traps() -> Array:
	var a: Array = level.get("allowed_traps", [])
	if a.is_empty():
		for k in Cfg.traps.keys():
			if not String(k).begins_with("_"):
				a.append(k)
	return a

func trap_names() -> Dictionary:
	var d := {}
	for id in Cfg.traps.keys():
		if String(id).begins_with("_"):
			continue
		d[id] = String(Cfg.traps[id].get("name", id))
	return d

func set_speed_index(i: int) -> void:
	var speeds := Cfg.arr("sim.speeds", [0.5, 1.0, 2.0, 4.0])
	speed_index = clampi(i, 0, speeds.size() - 1)
	sim_speed = float(speeds[speed_index])
	changed.emit()

func toggle_sandbox() -> void:
	sandbox = not sandbox
	if sandbox:
		gold = Cfg.int_at("debug.sandbox_gold", 99999)
		_log("沙盒模式开启：无限金币、随时可施工，Z/C/V/B 按 enemies.json 顺序手动放怪")
	else:
		gold = Cfg.int_at("economy.start_gold", 300)
		_log("沙盒模式关闭")
	changed.emit()

func sandbox_spawn(enemy_id: String, count: int) -> void:
	if not sandbox:
		return
	if phase != Phase.COMBAT:
		phase = Phase.COMBAT
		_acc = 0.0
	for i in count:
		spawn(enemy_id)
	_log("沙盒放怪：%s x%d" % [String(Cfg.enemies.get(enemy_id, {}).get("name", enemy_id)), count])
	changed.emit()

func export_log() -> String:
	var dir := "user://logs"
	DirAccess.make_dir_recursive_absolute(dir)
	var stamp := Time.get_datetime_string_from_system().replace(":", "-")
	var path := "%s/run_seed%d_%s.log" % [dir, seed_value, stamp]
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return ""
	f.store_string(stats.to_text(trap_names()))
	f.close()
	return ProjectSettings.globalize_path(path)

func _log(line: String) -> void:
	stats.add_log(line)
	logged.emit(line)
