extends Node
## 无头自动化测试。运行：
##   Godot_v4.7-stable_win64_console.exe --headless --path . res://tests/run_tests.tscn
## 覆盖文档 21 要求的三组验证：小怪可被连续击飞处决 / 中型需累计冲击 / 重型只短移并撞伤小怪。

const STEP := 1.0 / 60.0

var _failures: int = 0
var _lines: PackedStringArray = PackedStringArray()

func _ready() -> void:
	_run("T0 关卡与入口推导", _test_level)
	_run("T1 小怪被弹射板击飞并坠落处决", _test_small_launch_fall)
	_run("T2 中型敌人需累计冲击才位移", _test_medium_accumulate)
	_run("T3 重型只短移，且撞伤沿途小怪", _test_heavy_short_push)
	_run("T4 完整一波跑通不崩溃", _test_full_wave)
	_run("T6 关卡可以显式指定入口", _test_entrance_override)
	_run("T7 机关模型与触发动作", _test_trap_view)
	await _run_scene_test()

	print("\n".join(_lines))
	if _failures == 0:
		print("\n全部测试通过 ✓")
	else:
		print("\n失败 %d 项 ✗" % _failures)
	get_tree().quit(0 if _failures == 0 else 1)

## T5 需要真实场景（相机/界面），单独处理
func _run_scene_test() -> void:
	var errs := PackedStringArray()
	var m = load("res://scenes/main.tscn").instantiate()
	add_child(m)
	# main.gd 有语法错时脚本会整个挂不上，节点退化成裸 Node3D，
	# 后面的断言全被跳过还报"通过" —— 先把这种情况揪出来
	if m.get_script() == null or not m.has_method("switch_level"):
		_check(false, "main.tscn 的脚本没挂上（多半是 main.gd 解析失败，看上面的报错）", errs)
		_run_result("T5 场景启动、鼠标拾取与界面回调", errs)
		return
	m.switch_level("corridor_01")      # 默认关卡可配，这里的坐标断言只对走廊关成立
	if m.game.load_error != "":
		errs.append(m.game.load_error)
	else:
		# 地面格拾取
		var cell := Vector2i(6, 15)
		var hit: Dictionary = m.cell_at_screen(m.cam.unproject_position(m.game.grid.cell_center(cell)))
		_check(hit["cell"] == cell, "地面拾取错误：期望 %s，实为 %s" % [str(cell), str(hit["cell"])], errs)
		# 墙顶拾取（视觉上点的是墙顶而不是墙脚）
		var wcell := Vector2i(3, 12)
		var wtop: Vector3 = m.game.grid.cell_center(wcell) + Vector3(0, m.game.wall_height, 0)
		var whit: Dictionary = m.cell_at_screen(m.cam.unproject_position(wtop))
		_check(whit["cell"] == wcell and bool(whit["on_wall"]), "墙面拾取错误：%s" % str(whit["cell"]), errs)
		# 面选择：鼠标偏在墙格西侧 → 选西面（东面被另一面墙挡住，不应选中）
		var west: Vector3 = m.game.grid.cell_center(wcell) + Vector3(-0.8, 0, 0)
		_check(m.pick_wall_face(wcell, west) == Vector2i(-1, 0), "西侧应选中西面", errs)
		var east: Vector3 = m.game.grid.cell_center(wcell) + Vector3(0.8, 0, 0)
		_check(m.pick_wall_face(wcell, east) != Vector2i(1, 0), "东面挨着另一面墙，不该被选中", errs)
		# 界面回调齐全
		for cb in ["on_speed", "on_pause", "on_start_wave", "on_restart", "on_sandbox",
				"on_toggle_stats", "on_reload_config", "on_export_log", "select_trap"]:
			_check(m.has_method(cb), "main.gd 缺少界面回调 %s()" % cb, errs)
	# 让主场景真跑几帧，捕捉 _process / 界面刷新里的运行时错误
	for i in 5:
		await get_tree().process_frame
	m.queue_free()
	_run_result("T5 场景启动、鼠标拾取与界面回调", errs)

# ---------------------------------------------------------------- 框架

func _run(title: String, fn: Callable) -> void:
	_run_result(title, fn.call())

func _run_result(title: String, errs: PackedStringArray) -> void:
	if errs.is_empty():
		_lines.append("[通过] " + title)
	else:
		_failures += 1
		_lines.append("[失败] " + title)
		for e in errs:
			_lines.append("        " + e)

func _new_game() -> Game:
	var g := Game.new()
	add_child(g)
	g.paused = true          # 关掉 _process，测试里手动推进
	g.start("corridor_01")
	g.phase = Game.Phase.COMBAT
	return g

func _advance(g: Game, seconds: float) -> void:
	var steps := int(seconds / STEP)
	for i in steps:
		g.step_sim(STEP)

func _check(cond: bool, msg: String, errs: PackedStringArray) -> void:
	if not cond:
		errs.append(msg)

# ---------------------------------------------------------------- 用例

## T7：五种机关都要能载入模型、找到活动部件，触发后部件必须动起来。
## 靠截图抓那一帧全是运气，直接比 transform 才是可靠的。
func _test_trap_view() -> PackedStringArray:
	var errs := PackedStringArray()
	var cs := 2.0
	for id in ["spikes", "tar", "launcher", "push_wall", "saw"]:
		var d: Dictionary = Cfg.traps.get(id, {})
		var model := String(d.get("model", ""))
		_check(model != "", "%s 没配 model" % id, errs)
		var anim: Dictionary = d.get("anim", {})
		_check(not anim.is_empty(), "%s 没配 anim" % id, errs)
		if model == "" or anim.is_empty():
			continue

		var v := TrapView.new()
		add_child(v)
		var loaded := v.setup(model, cs, Color.WHITE, anim)
		_check(loaded, "%s 模型 %s 载入失败" % [id, model], errs)
		if loaded:
			_check(v.part != null, "%s 在模型里找不到活动部件 %s" %
				[id, String(anim.get("part", ""))], errs)
			if v.part != null:
				var rest := v.part.transform
				var kind := String(anim.get("type", ""))
				if kind == "spin" or kind == "bob":
					v.step(0.5)          # 待机动作，不用触发
				else:
					v.fire()
					v.step(float(anim.get("attack", 0.06)))
				var moved := not v.part.transform.is_equal_approx(rest)
				_check(moved, "%s 触发后活动部件没动（anim.axis 方向可能不对）" % id, errs)
		v.free()
	return errs

func _test_level() -> PackedStringArray:
	var errs := PackedStringArray()
	var g := _new_game()
	_check(g.load_error == "", "关卡载入失败: " + g.load_error, errs)
	if g.load_error != "":
		return errs
	_check(g.grid.w == 14 and g.grid.h == 20, "网格尺寸异常: %dx%d" % [g.grid.w, g.grid.h], errs)
	_check(g.core_cells.size() == 4, "核心格数应为 4，实为 %d" % g.core_cells.size(), errs)
	_check(g.entrance_cells.size() == 5, "入口应为底边 5 格，实为 %d" % g.entrance_cells.size(), errs)
	for c in g.entrance_cells:
		_check(c.y == g.grid.h - 1, "入口不在离核心最远的底边: %s" % str(c), errs)
	# 墙面放置规则：成片墙的外侧面可用，内侧被挡的面不可用
	var wall := Vector2i(3, 5)      # 2x2 墙块的左上角
	_check(g.grid.is_wall(wall), "(3,5) 应该是墙", errs)
	_check(g.grid.wall_face_free(wall, Vector2i(-1, 0)), "墙块左面应可放机关", errs)
	_check(g.grid.wall_face_free(wall, Vector2i(0, -1)), "墙块上面应可放机关", errs)
	_check(not g.grid.wall_face_free(wall, Vector2i(1, 0)), "墙块右面挨着另一面墙，不该可放", errs)
	_check(not g.grid.wall_face_free(wall, Vector2i(0, 1)), "墙块下面挨着另一面墙，不该可放", errs)
	g.queue_free()
	return errs

func _test_small_launch_fall() -> PackedStringArray:
	var errs := PackedStringArray()
	var g := _new_game()
	if g.load_error != "":
		return PackedStringArray([g.load_error])
	g.phase = Game.Phase.BUILD
	var pad := Vector2i(2, 11)                 # 坑南侧的地面
	var placed := g.place("launcher", pad, Vector2i(0, -1))   # 朝北，正对深坑
	_check(placed, "弹射板放置失败", errs)
	g.phase = Game.Phase.COMBAT

	var e := g.spawn_at("grunt", pad)
	e.position = g.grid.cell_center(pad)       # 去掉随机偏移，保证可复现
	var thrown := false
	var fell := false
	for i in int(4.0 / STEP):
		g.step_sim(STEP)
		if is_instance_valid(e):
			if e.state == Enemy.State.THROWN:
				thrown = true
			if e.state == Enemy.State.FALLING:
				fell = true
		else:
			break
	_check(thrown, "小怪没有被击飞", errs)
	_check(fell, "小怪没有掉进空地", errs)
	_check(int(g.stats.kills_by_cause.get("fall", 0)) == 1, "坠落处决应记 1 次，实为 %d" % int(g.stats.kills_by_cause.get("fall", 0)), errs)
	var slot: Dictionary = g.stats.per_trap.get("launcher", {})
	_check(int(slot.get("displacements", 0)) >= 1, "弹射板位移次数未统计", errs)
	g.queue_free()
	return errs

func _test_medium_accumulate() -> PackedStringArray:
	var errs := PackedStringArray()
	var g := _new_game()
	if g.load_error != "":
		return PackedStringArray([g.load_error])
	var push_force := float(Cfg.traps["push_wall"]["displacement"]["force"])

	var small := g.spawn_at("grunt", Vector2i(6, 14))
	small.apply_impulse(Vector3(1, 0, 0), push_force, 0.18, "test")
	_check(small.state == Enemy.State.THROWN, "小型敌人应当一次推墙就被位移", errs)

	var mid := g.spawn_at("berserker", Vector2i(7, 14))
	mid.apply_impulse(Vector3(1, 0, 0), push_force, 0.18, "test")
	_check(mid.state == Enemy.State.GROUND, "中型敌人不该被单次推墙位移", errs)
	_check(is_equal_approx(mid.impact, push_force), "中型冲击积累应为 %.1f，实为 %.1f" % [push_force, mid.impact], errs)
	mid.apply_impulse(Vector3(1, 0, 0), push_force, 0.18, "test")
	_check(mid.state == Enemy.State.THROWN, "两次推墙累计 %.0f ≥ 稳定值 %.0f，应当位移" % [push_force * 2.0, mid.stability], errs)
	_check(is_zero_approx(mid.impact), "位移后冲击槽应清零", errs)

	# 单次弹射板（力 15）仍然打不动中型（稳定值 18）
	var mid2 := g.spawn_at("berserker", Vector2i(8, 14))
	var launch_force := float(Cfg.traps["launcher"]["displacement"]["force"])
	mid2.apply_impulse(Vector3(1, 0, 0), launch_force, 0.75, "test")
	_check(mid2.state == Enemy.State.GROUND, "单次弹射板不该击飞中型敌人", errs)

	g.queue_free()
	return errs

func _test_heavy_short_push() -> PackedStringArray:
	var errs := PackedStringArray()
	var g := _new_game()
	if g.load_error != "":
		return PackedStringArray([g.load_error])

	var heavy := g.spawn_at("troll", Vector2i(4, 15))
	heavy.position = g.grid.cell_center(Vector2i(4, 15))
	var victim := g.spawn_at("grunt", Vector2i(5, 15))
	victim.position = heavy.position + Vector3(1.15, 0, 0)
	var victim_hp := victim.hp

	var pushes := 0
	while heavy.state == Enemy.State.GROUND and pushes < 20:
		heavy.apply_impulse(Vector3(1, 0, 0), 9.0, 0.18, "test")
		pushes += 1
	_check(pushes >= 5, "重型敌人应当需要 5 次以上推墙才位移，实际 %d 次" % pushes, errs)

	var start_x := heavy.position.x
	var heavy_speed := heavy.speed_h()
	_advance(g, 2.0)
	var moved: float = absf(heavy.position.x - start_x)
	_check(heavy_speed < 4.0, "重型位移速度应明显低于小型，实为 %.1f" % heavy_speed, errs)
	_check(moved < g.grid.cell_size * 3.0, "重型位移距离应该短，实为 %.1f 米" % moved, errs)
	_check(victim.hp < victim_hp or not is_instance_valid(victim) or victim.state == Enemy.State.DEAD,
		"重型冲过去应该撞伤沿途小怪", errs)
	_check(int(g.stats.kills_by_cause.get("collision", 0)) >= 1 or victim.hp < victim_hp,
		"撞击伤害没有被统计", errs)
	g.queue_free()
	return errs

func _test_entrance_override() -> PackedStringArray:
	var errs := PackedStringArray()
	# 走廊关没写 entrance，走自动推导：底边那段最远的开口
	var g := _new_game()
	_check(g.entrance_cells.size() == 5, "走廊关应自动推出 5 格入口，实为 %d" % g.entrance_cells.size(), errs)
	g.queue_free()

	# 地牢关写了 entrance，应当严格按写的来
	if not Cfg.levels.has("dw_01"):
		errs.append("找不到 dw_01 关卡")
		return errs
	var g2 := Game.new()
	add_child(g2)
	g2.paused = true
	g2.start("dw_01")
	_check(g2.load_error == "", "dw_01 载入失败: " + g2.load_error, errs)
	if g2.load_error == "":
		# 不写死坐标 —— 关卡随时会被手工调整；这里验证的是"以关卡里写的为准"这个机制
		var spec: Variant = Cfg.levels["dw_01"].get("entrance", null)
		_check(spec != null, "dw_01 应当写了 entrance 字段", errs)
		if spec != null:
			var listed: Array[Vector2i] = g2._parse_cells(spec)
			_check(not g2.entrance_cells.is_empty(), "入口不该为空", errs)
			for c in g2.entrance_cells:
				_check(listed.has(c), "入口 %s 不在关卡写的 entrance 里，说明没按关卡来" % str(c), errs)
	g2.queue_free()
	return errs

func _test_full_wave() -> PackedStringArray:
	var errs := PackedStringArray()
	var g := _new_game()
	if g.load_error != "":
		return PackedStringArray([g.load_error])
	g.phase = Game.Phase.BUILD
	g.gold = 9999
	_check(g.place("tar", Vector2i(6, 11), Vector2i(0, -1)), "黏胶放置失败", errs)
	_check(g.place("tar", Vector2i(7, 11), Vector2i(0, -1)), "黏胶放置失败", errs)
	_check(g.place("spikes", Vector2i(6, 9), Vector2i(0, -1)), "桥面地刺放置失败", errs)
	_check(g.place("push_wall", Vector2i(5, 9), Vector2i(1, 0)), "推墙放置失败（桥西侧墙柱）", errs)
	_check(g.place("saw", Vector2i(8, 9), Vector2i(-1, 0)), "锯墙放置失败（桥东侧墙柱）", errs)
	_check(not g.place("saw", Vector2i(3, 12), Vector2i(1, 0)), "被另一面墙挡住的面不该允许放置", errs)
	_check(not g.place("spikes", Vector2i(0, 0), Vector2i(0, -1)), "墙格不该允许放地面机关", errs)
	_check(not g.place("spikes", Vector2i(2, 9), Vector2i(0, -1)), "空地不该允许放地面机关", errs)

	_check(g.start_wave(), "开始波次失败", errs)
	var guard := 0
	while g.phase == Game.Phase.COMBAT and guard < int(120.0 / STEP):
		g.step_sim(STEP)
		guard += 1
	_check(g.phase != Game.Phase.COMBAT, "第一波在 120 秒内没有结束", errs)
	_check(g.stats.damage_total > 0.0, "整波没有任何伤害记录", errs)
	_check(g.stats.kills_total + g.stats.leaks == 8, "8 只小兵应当各有归宿，实为 击杀%d + 漏怪%d" % [g.stats.kills_total, g.stats.leaks], errs)
	_check(int(g.stats.kills_by_cause.get("fall", 0)) >= 1, "推墙应当至少把一只怪推下桥", errs)
	_lines.append("        第1波结果：击杀 %d，漏怪 %d，坠落 %d，剩余核心 %d" % [
		g.stats.kills_total, g.stats.leaks, int(g.stats.kills_by_cause.get("fall", 0)), g.core_hp])
	g.queue_free()
	return errs
