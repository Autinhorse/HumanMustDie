extends Node3D
## 入口：搭相机、灯光、地图表现、界面，并处理放置输入。

var game: Game = null
var board: BoardView = null
var preview: PlacementPreview = null
var hud: Hud = null

var _pivot: Node3D = null
var cam: Camera3D = null
var _yaw := 0.0
var _dist := 60.0
var _pitch := -52.0
var _ortho_size := 46.0
var _backdrop: MeshInstance3D = null

var pending_trap_id: String = ""
var pending_facing := Vector2i(0, -1)
var place_error_text: String = ""
var selected_trap: Trap = null
var _face_cycle := 0
var _hover_cell := Vector2i(-1, -1)
var _hover_valid := false

func _ready() -> void:
	if Cfg.errors.size() > 0:
		push_error("配置载入有错误，见输出面板")
	_build_world()
	game = Game.new()
	game.name = "Game"
	add_child(game)
	game.start("corridor_01")

	board = BoardView.new()
	add_child(board)
	preview = PlacementPreview.new()
	add_child(preview)
	hud = Hud.new()
	add_child(hud)
	hud.setup(game, self)
	_refresh_board()

func _refresh_board() -> void:
	if game.load_error != "":
		hud.refresh()
		return
	board.build(game.grid, game.entrance_cells)
	preview.setup(game.grid)
	_pivot.position = game.grid.center_world()
	_dist = Cfg.num("camera.distance", 60.0)
	_yaw = Cfg.num("camera.yaw_deg", -40.0)
	_pitch = Cfg.num("camera.pitch_deg", -52.0)
	_ortho_size = Cfg.num("camera.ortho_size", 46.0)
	_update_camera()
	hud.rebuild_build_bar()
	hud.refresh()

func _build_world() -> void:
	var env_cfg: Dictionary = Cfg.art.get("environment", {})

	var env := WorldEnvironment.new()
	env.environment = _make_environment(env_cfg)
	add_child(env)

	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	var elev := deg_to_rad(_ec(env_cfg, "sun_elevation_deg", 42.0))
	var azim := deg_to_rad(_ec(env_cfg, "sun_azimuth_deg", 35.0))
	sun.rotation = Vector3(-elev, azim, 0.0)
	sun.light_color = _hex(env_cfg, "sun_color", Color(1.0, 0.96, 0.91))
	sun.light_energy = _ec(env_cfg, "sun_energy", 1.9)
	sun.light_angular_distance = _ec(env_cfg, "sun_angular_distance_deg", 3.5)
	sun.shadow_enabled = true
	sun.shadow_blur = _ec(env_cfg, "shadow_blur", 1.4)
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	sun.directional_shadow_max_distance = 200.0
	add_child(sun)

	# 补光：把阴影面提亮成天空色，避免暗部发死
	var fill := DirectionalLight3D.new()
	fill.name = "Fill"
	fill.rotation = Vector3(deg_to_rad(-28.0), azim + PI * 0.85, 0.0)
	fill.light_color = _hex(env_cfg, "fill_color", Color(0.75, 0.84, 0.84))
	fill.light_energy = _ec(env_cfg, "fill_energy", 0.45)
	fill.shadow_enabled = false
	add_child(fill)

	_pivot = Node3D.new()
	add_child(_pivot)
	cam = Camera3D.new()
	_pivot.add_child(cam)
	_build_backdrop(env_cfg)
	_update_camera()

## 渐变背板：挂在相机上，永远铺满画面。正交投影下程序天空会算出条带，所以自己画。
func _build_backdrop(env_cfg: Dictionary) -> void:
	var grad := Gradient.new()
	grad.set_color(0, _hex(env_cfg, "sky_top", Color(0.42, 0.55, 0.57)))
	grad.set_color(1, _hex(env_cfg, "sky_horizon", Color(0.65, 0.76, 0.75)))
	grad.add_point(0.62, _hex(env_cfg, "ground_horizon", Color(0.56, 0.66, 0.66)))
	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.width = 8
	tex.height = 512
	tex.fill_from = Vector2(0, 0)
	tex.fill_to = Vector2(0, 1)

	var mat := StandardMaterial3D.new()
	mat.albedo_texture = tex
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR

	_backdrop = MeshInstance3D.new()
	_backdrop.name = "Backdrop"
	_backdrop.mesh = QuadMesh.new()
	_backdrop.material_override = mat
	_backdrop.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	cam.add_child(_backdrop)

func _make_environment(env_cfg: Dictionary) -> Environment:
	var e := Environment.new()

	e.background_mode = Environment.BG_COLOR
	e.background_color = _hex(env_cfg, "sky_horizon", Color(0.65, 0.76, 0.75))
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = _hex(env_cfg, "ambient_color", _hex(env_cfg, "sky_horizon", Color(0.65, 0.76, 0.75)))
	e.ambient_light_energy = _ec(env_cfg, "ambient_energy", 0.85)

	match String(env_cfg.get("tonemap", "filmic")):
		"linear":
			e.tonemap_mode = Environment.TONE_MAPPER_LINEAR
		"aces":
			e.tonemap_mode = Environment.TONE_MAPPER_ACES
		"agx":
			e.tonemap_mode = Environment.TONE_MAPPER_AGX
		_:
			e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	e.tonemap_exposure = _ec(env_cfg, "exposure", 1.0)
	e.tonemap_white = _ec(env_cfg, "white", 1.1)

	if bool(env_cfg.get("fog_enabled", true)):
		e.fog_enabled = true
		e.fog_light_color = _hex(env_cfg, "fog_color", Color(0.83, 0.89, 0.87))
		e.fog_density = _ec(env_cfg, "fog_density", 0.006)
		e.fog_sky_affect = _ec(env_cfg, "fog_sky_affect", 0.0)
		e.fog_aerial_perspective = _ec(env_cfg, "fog_aerial_perspective", 0.35)

	if bool(env_cfg.get("ssao_enabled", true)):
		e.ssao_enabled = true
		e.ssao_radius = _ec(env_cfg, "ssao_radius", 1.4)
		e.ssao_intensity = _ec(env_cfg, "ssao_intensity", 1.6)
		e.ssao_power = _ec(env_cfg, "ssao_power", 1.5)
	return e

func _ec(d: Dictionary, key: String, def: float) -> float:
	if d.has(key):
		return float(d[key])
	return def

func _hex(d: Dictionary, key: String, def: Color) -> Color:
	if d.has(key) and typeof(d[key]) == TYPE_STRING:
		return Color(String(d[key]))
	return def

func _update_camera() -> void:
	_pivot.rotation_degrees.y = _yaw
	var pitch := deg_to_rad(_pitch)
	cam.position = Vector3(0.0, -sin(pitch) * _dist, cos(pitch) * _dist)
	cam.rotation = Vector3(pitch, 0.0, 0.0)
	if Cfg.str_at("camera.projection", "orthogonal") == "perspective":
		cam.projection = Camera3D.PROJECTION_PERSPECTIVE
	else:
		cam.projection = Camera3D.PROJECTION_ORTHOGONAL
		cam.size = _ortho_size
	cam.near = 0.1
	cam.far = _dist * 4.0
	if _backdrop != null:
		var vp := get_viewport().get_visible_rect().size
		var aspect: float = vp.x / max(vp.y, 1.0)
		_backdrop.mesh.size = Vector2(_ortho_size * aspect * 1.05, _ortho_size * 1.05)
		_backdrop.position = Vector3(0, 0, -cam.far * 0.9)

# ---------------------------------------------------------------- 每帧

func _process(delta: float) -> void:
	_handle_camera_pan(delta)
	_update_hover()
	hud.refresh()

func _handle_camera_pan(delta: float) -> void:
	var dir := Vector2.ZERO
	if Input.is_key_pressed(KEY_W):
		dir.y -= 1.0
	if Input.is_key_pressed(KEY_S):
		dir.y += 1.0
	if Input.is_key_pressed(KEY_A):
		dir.x -= 1.0
	if Input.is_key_pressed(KEY_D):
		dir.x += 1.0
	if dir == Vector2.ZERO:
		return
	var speed := Cfg.num("camera.pan_speed", 22.0) * delta
	var yaw := deg_to_rad(_yaw)
	var forward := Vector3(sin(yaw), 0, cos(yaw))
	var right := Vector3(cos(yaw), 0, -sin(yaw))
	_pivot.position += (forward * dir.y + right * dir.x) * speed

## 鼠标射线打到 y=0 与 y=墙高 两个平面，优先取墙顶（视觉上用户点的是墙）
func _mouse_cell() -> Dictionary:
	return cell_at_screen(get_viewport().get_mouse_position())

## 屏幕坐标 -> 网格格子。抽出来是为了能在无头测试里直接验证拾取。
func cell_at_screen(mp: Vector2) -> Dictionary:
	var out := {"cell": Vector2i(-1, -1), "point": Vector3.ZERO, "on_wall": false}
	if game.grid == null or cam == null:
		return out
	var from := cam.project_ray_origin(mp)
	var dir := cam.project_ray_normal(mp)
	if absf(dir.y) < 0.0001:
		return out
	var wall_h := game.wall_height
	var p_top := from + dir * ((wall_h - from.y) / dir.y)
	var cell_top := game.grid.world_to_cell(p_top)
	if game.grid.is_wall(cell_top):
		out["cell"] = cell_top
		out["point"] = p_top
		out["on_wall"] = true
		return out
	var p0 := from + dir * (-from.y / dir.y)
	out["cell"] = game.grid.world_to_cell(p0)
	out["point"] = p0
	return out

func _update_hover() -> void:
	if game.load_error != "" or preview == null:
		return
	var hit := _mouse_cell()
	_hover_cell = hit["cell"]
	if pending_trap_id == "":
		_show_selected_coverage()
		return
	var data: Dictionary = Cfg.traps.get(pending_trap_id, {})
	var mount := String(data.get("mount", "ground"))
	if not game.grid.in_bounds(_hover_cell):
		preview.clear()
		_hover_valid = false
		return

	if mount == "wall":
		pending_facing = pick_wall_face(_hover_cell, hit["point"])
	elif bool(data.get("directional", false)):
		pending_facing = _directional_facing(_hover_cell)
	else:
		pending_facing = Vector2i(0, -1)

	var check := game.can_place(pending_trap_id, _hover_cell, pending_facing)
	_hover_valid = bool(check["ok"])
	place_error_text = "" if _hover_valid else "  —  " + String(check["reason"])
	var cells := TrapTargeting.compute(data.get("targeting", {}), _hover_cell, pending_facing, game.grid)
	preview.show_cells(cells, _hover_cell, pending_facing, "ok" if _hover_valid else "bad",
		bool(data.get("directional", false)), 0.06 if mount == "ground" else game.wall_height + 0.06)

func _show_selected_coverage() -> void:
	if selected_trap == null or not is_instance_valid(selected_trap):
		selected_trap = null
		preview.clear()
		return
	var lift: float = 0.06 if selected_trap.mount == "ground" else game.wall_height + 0.06
	preview.show_cells(selected_trap.coverage, selected_trap.cell, selected_trap.facing, "select",
		bool(selected_trap.data.get("directional", false)), lift)

## 墙面机关：按鼠标在墙格内的偏移选最近的暴露面，R 键在可用面之间循环
func pick_wall_face(cell: Vector2i, point: Vector3) -> Vector2i:
	var faces := game.grid.exposed_faces(cell)
	if faces.is_empty():
		return Vector2i(0, -1)
	var center := game.grid.cell_center(cell)
	var off := Vector2(point.x - center.x, point.z - center.z)
	if off.length() < 0.001:
		off = Vector2(0, -1)
	off = off.normalized()
	var sorted := faces.duplicate()
	sorted.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		return Vector2(a.x, a.y).dot(off) > Vector2(b.x, b.y).dot(off))
	return sorted[_face_cycle % sorted.size()]

## 地面方向机关：默认顺着敌人前进方向，R 键改成四向
func _directional_facing(cell: Vector2i) -> Vector2i:
	var base := Vector2i(0, -1)
	if game.flow != null and game.flow.reachable(cell):
		var n: Vector2i = game.flow.next_cell(cell)
		if n != cell:
			base = n - cell
	var order := [base, Vector2i(-base.y, base.x), -base, Vector2i(base.y, -base.x)]
	return order[_face_cycle % 4]

# ---------------------------------------------------------------- 输入

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		match event.button_index:
			MOUSE_BUTTON_LEFT:
				_on_click()
			MOUSE_BUTTON_RIGHT:
				_cancel()
			MOUSE_BUTTON_WHEEL_UP:
				_zoom(-1)
			MOUSE_BUTTON_WHEEL_DOWN:
				_zoom(1)
		return
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	var k: int = event.keycode
	match k:
		KEY_ESCAPE:
			_cancel()
		KEY_R:
			_face_cycle += 1
		KEY_SPACE:
			on_pause()
		KEY_ENTER, KEY_KP_ENTER:
			on_start_wave()
		KEY_TAB:
			on_toggle_stats()
		KEY_F1:
			on_sandbox()
		KEY_F2:
			on_restart()
		KEY_F5:
			on_reload_config()
		KEY_F12:
			_save_screenshot()
		KEY_X:
			if selected_trap != null and is_instance_valid(selected_trap):
				game.sell(selected_trap)
				selected_trap = null
				preview.clear()
		KEY_Q:
			_yaw -= Cfg.num("camera.yaw_step_deg", 45.0)
			_update_camera()
		KEY_E:
			_yaw += Cfg.num("camera.yaw_step_deg", 45.0)
			_update_camera()
		KEY_Z:
			game.sandbox_spawn("grunt", 8)
		KEY_C:
			game.sandbox_spawn("berserker", 3)
		KEY_V:
			game.sandbox_spawn("troll", 1)
		_:
			var allowed := game.allowed_traps()
			for i in allowed.size():
				if k == KEY_1 + i and i < 9:
					select_trap(String(allowed[i]))
					break

func _zoom(sign_dir: int) -> void:
	_ortho_size = clampf(_ortho_size + float(sign_dir) * Cfg.num("camera.zoom_step", 3.0),
		Cfg.num("camera.ortho_min", 12.0), Cfg.num("camera.ortho_max", 90.0))
	_update_camera()

func _on_click() -> void:
	if game.load_error != "":
		return
	var hit := _mouse_cell()
	var cell: Vector2i = hit["cell"]
	if pending_trap_id != "":
		if game.place(pending_trap_id, cell, pending_facing):
			if not Input.is_key_pressed(KEY_SHIFT):
				pending_trap_id = ""
				preview.clear()
		return
	# 无待放置机关：先查敌人，再查机关
	var e = _enemy_near(hit["point"])
	if e != null:
		selected_trap = null
		hud.set_inspect(e.status_text())
		return
	var t := game.trap_at_cell(cell)
	if t != null:
		selected_trap = t
		hud.set_inspect("%s（%s）  冷却 %.0f%%  X 键拆除" % [t.display_name(), String(t.data.get("desc", "")), t.cooldown_ratio() * 100.0])
	else:
		selected_trap = null
		var ct := game.grid.get_cell(cell)
		hud.set_inspect("格子 (%d,%d) %s" % [cell.x, cell.y, String(HGrid.CELL_NAMES.get(ct, "?"))])

func _enemy_near(point: Vector3):
	var best = null
	var best_d := 1.2
	for e in game.enemies:
		var d: float = Vector2(e.position.x - point.x, e.position.z - point.z).length()
		if d < best_d:
			best_d = d
			best = e
	return best

func _cancel() -> void:
	pending_trap_id = ""
	place_error_text = ""
	selected_trap = null
	preview.clear()

# ---------------------------------------------------------------- HUD 回调

func select_trap(id: String) -> void:
	if pending_trap_id == id:
		_cancel()
		return
	pending_trap_id = id
	selected_trap = null
	_face_cycle = 0
	place_error_text = ""

func on_speed(i: int) -> void:
	game.set_speed_index(i)

func on_pause() -> void:
	game.paused = not game.paused
	game.changed.emit()

func on_start_wave() -> void:
	game.start_wave()

func on_restart() -> void:
	_cancel()
	game.reset()
	_refresh_board()

func on_sandbox() -> void:
	game.toggle_sandbox()

func on_toggle_stats() -> void:
	hud.toggle_stats()

func on_reload_config() -> void:
	Cfg.load_all()
	_cancel()
	game.reset()
	_refresh_board()

func _save_screenshot() -> void:
	await RenderingServer.frame_post_draw
	DirAccess.make_dir_recursive_absolute("user://shots")
	var path := "user://shots/shot_%s.png" % Time.get_datetime_string_from_system().replace(":", "-")
	var img := get_viewport().get_texture().get_image()
	if img.save_png(path) == OK:
		hud.set_inspect("截图已保存：" + ProjectSettings.globalize_path(path))
	else:
		hud.set_inspect("截图保存失败")

func on_export_log() -> void:
	var path := game.export_log()
	if path == "":
		hud.set_inspect("日志导出失败")
	else:
		hud.set_inspect("日志已导出：" + path)
