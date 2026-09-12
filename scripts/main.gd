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
var _clouds: Array[MeshInstance3D] = []
var _outline: MeshInstance3D = null
var fx: Fx = null

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
	game.start(_level_from_cmdline())
	game.changed.connect(_on_game_changed)

	fx = Fx.new()
	fx.name = "Fx"
	fx.setup(Cfg.art.get("fx", {}))
	add_child(fx)

	board = BoardView.new()
	add_child(board)
	preview = PlacementPreview.new()
	add_child(preview)
	hud = Hud.new()
	add_child(hud)
	hud.setup(game, self)
	_refresh_board()

## 命令行选关：--level <id>，默认走廊关
func _level_from_cmdline() -> String:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--level" and i + 1 < args.size():
			return String(args[i + 1])
	var d := Cfg.str_at("sim.default_level", "corridor_01")
	return d if Cfg.levels.has(d) else "corridor_01"

## 切换关卡（界面下拉框用）
func switch_level(id: String) -> void:
	if game.level_id == id or not Cfg.levels.has(id):
		return
	_cancel()
	game.start(id)
	_refresh_board()

## 哪些格子要把地板让开：放了 cuts_floor 机关的格子。
## 机关是运行时放的，所以放置/拆除以后要重建一次地块网格。
func _pit_cells() -> Dictionary:
	var out: Dictionary = {}
	if game == null or game.grid == null:
		return out
	for t in game.trap_list():
		if bool(t.data.get("cuts_floor", false)):
			out[t.cell] = true
	return out

## 地板要不要让开是跟着机关走的。挂在 game.changed 上而不是放置回调上 ——
## 放置有好几条路径（界面点击、演示脚本直接调 place、读档），挂回调会漏。
var _pit_sig: Array = []

func _on_game_changed() -> void:
	if game.load_error != "":
		return
	var cells: Dictionary = _pit_cells()
	var sig: Array = cells.keys()
	sig.sort()
	if sig == _pit_sig:
		return
	_pit_sig = sig
	board.build(game.grid, game.entrance_cells, cells)

func _refresh_board() -> void:
	if game.load_error != "":
		hud.refresh()
		return
	var cells: Dictionary = _pit_cells()
	var sig: Array = cells.keys()
	sig.sort()
	_pit_sig = sig
	board.build(game.grid, game.entrance_cells, cells)
	preview.setup(game.grid)
	_pivot.position = game.grid.center_world()
	_dist = Cfg.num("camera.distance", 60.0)
	_yaw = Cfg.num("camera.yaw_deg", -40.0)
	_pitch = Cfg.num("camera.pitch_deg", -52.0)
	_ortho_size = Cfg.num("camera.ortho_size", 46.0)
	_update_camera()
	if Cfg.num("camera.auto_fit", 1.0) > 0.0:
		_fit_camera_to_map()
	hud.rebuild_build_bar()
	hud.rebuild_level_list()
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
	sun.light_volumetric_fog_energy = _ec(env_cfg, "sun_volumetric_energy", 2.2)
	add_child(sun)

	# 补光：把阴影面提亮成天空色，避免暗部发死
	var fill := DirectionalLight3D.new()
	fill.name = "Fill"
	fill.rotation = Vector3(deg_to_rad(-28.0), azim + PI * 0.85, 0.0)
	fill.light_color = _hex(env_cfg, "fill_color", Color(0.75, 0.84, 0.84))
	fill.light_energy = _ec(env_cfg, "fill_energy", 0.45)
	fill.shadow_enabled = false
	add_child(fill)

	# 边缘光：从背后低角度打一道冷色，把物体从背景里剥出来
	if _ec(env_cfg, "rim_energy", 0.0) > 0.0:
		var rim := DirectionalLight3D.new()
		rim.name = "Rim"
		rim.rotation = Vector3(-deg_to_rad(_ec(env_cfg, "rim_elevation_deg", 12.0)),
			azim + deg_to_rad(_ec(env_cfg, "rim_azimuth_offset_deg", 155.0)), 0.0)
		rim.light_color = _hex(env_cfg, "rim_color", Color(0.72, 0.86, 0.95))
		rim.light_energy = _ec(env_cfg, "rim_energy", 0.5)
		rim.light_specular = 0.0
		rim.shadow_enabled = false
		add_child(rim)

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
	_build_clouds()
	_build_outline(env_cfg)

## 屏幕空间描边：一块全屏四边形挂在相机上，在所有东西画完之后覆盖一层
func _build_outline(env_cfg: Dictionary) -> void:
	if not bool(env_cfg.get("outline_enabled", true)):
		return
	var shader: Shader = load("res://assets/shaders/outline.gdshader")
	if shader == null:
		push_warning("描边着色器载入失败")
		return
	var m := ShaderMaterial.new()
	m.shader = shader
	m.render_priority = 100        # 保证最后画
	m.set_shader_parameter("outline_color", _hex(env_cfg, "outline_color", Color(0.11, 0.13, 0.17)))
	m.set_shader_parameter("thickness", _ec(env_cfg, "outline_thickness", 1.0))
	m.set_shader_parameter("depth_threshold", _ec(env_cfg, "outline_depth_threshold", 0.045))
	m.set_shader_parameter("normal_threshold", _ec(env_cfg, "outline_normal_threshold", 0.30))
	m.set_shader_parameter("strength", _ec(env_cfg, "outline_strength", 0.8))
	m.set_shader_parameter("depth_fade", _ec(env_cfg, "outline_depth_fade", 120.0))

	_outline = MeshInstance3D.new()
	_outline.name = "Outline"
	_outline.mesh = QuadMesh.new()
	_outline.material_override = m
	_outline.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	# 顶点着色器会把它拉成全屏，这里只要保证不被视锥剔除
	_outline.extra_cull_margin = 16384.0
	_outline.position = Vector3(0, 0, -1.0)
	cam.add_child(_outline)

## 云：参考图里是画在背景上的柔边薄雾，不是有体积的白球。
## 做成跟随相机的一层宽扁柔边片，和天空只差一点亮度，永远在所有东西后面。
func _build_clouds() -> void:
	_clouds.clear()
	var cfg: Dictionary = Cfg.art.get("clouds", {})
	if not bool(cfg.get("enabled", true)):
		return
	var pal: Dictionary = Cfg.art.get("palette", {})

	var grad := Gradient.new()
	var core_col: Color = _pal_color(pal, "cloud", Color(0.92, 0.96, 0.95))
	grad.set_color(0, Color(core_col.r, core_col.g, core_col.b, 1.0))
	grad.set_color(1, Color(core_col.r, core_col.g, core_col.b, 0.0))
	# 中间加一个点控制虚化程度：越靠外越软
	grad.add_point(float(cfg.get("softness", 0.45)), Color(core_col.r, core_col.g, core_col.b, 0.72))
	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.width = 256
	tex.height = 256
	tex.fill = GradientTexture2D.FILL_RADIAL
	tex.fill_from = Vector2(0.5, 0.5)
	tex.fill_to = Vector2(1.0, 0.5)

	var mat := StandardMaterial3D.new()
	mat.albedo_texture = tex
	mat.albedo_color = Color(1, 1, 1, float(cfg.get("alpha", 0.5)))
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED

	var rng := RandomNumberGenerator.new()
	rng.seed = int(Cfg.art.get("rock", {}).get("seed", 20260911)) + 31
	var aspect_min := float(cfg.get("aspect_min", 2.4))
	var aspect_max := float(cfg.get("aspect_max", 4.5))
	for i in int(cfg.get("count", 9)):
		var mi := MeshInstance3D.new()
		mi.mesh = QuadMesh.new()
		mi.material_override = mat
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		# 归一化的屏幕位置，偏向画面边缘；缩放时在 _update_camera 里跟着走
		var nx: float = rng.randf_range(-1.15, 1.15)
		var ny: float = rng.randf_range(-1.1, 1.1)
		if absf(nx) < 0.55 and absf(ny) < 0.5:
			ny = (1.0 if ny >= 0.0 else -1.0) * rng.randf_range(0.55, 1.1)
		mi.set_meta("nx", nx)
		mi.set_meta("ny", ny)
		mi.set_meta("nw", rng.randf_range(float(cfg.get("width_min", 0.5)), float(cfg.get("width_max", 1.1))))
		mi.set_meta("aspect", rng.randf_range(aspect_min, aspect_max))
		cam.add_child(mi)
		_clouds.append(mi)

func _pal_color(pal: Dictionary, key: String, def: Color) -> Color:
	if pal.has(key) and typeof(pal[key]) == TYPE_STRING:
		return Color(String(pal[key]))
	return def

func _make_environment(env_cfg: Dictionary) -> Environment:
	var e := Environment.new()

	e.background_mode = Environment.BG_COLOR
	e.background_color = _hex(env_cfg, "sky_horizon", Color(0.65, 0.76, 0.75))
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = _hex(env_cfg, "ambient_color", _hex(env_cfg, "sky_horizon", Color(0.65, 0.76, 0.75)))
	e.ambient_light_energy = _ec(env_cfg, "ambient_energy", 0.85)

	# 只给反射用的天空：背景仍然是纯色（正交相机下显示程序化天空会出一条斜带），
	# 但 reflection_source 指向天空以后，金属件才有东西可反射 ——
	# 没有这一步，金属反射的是一块纯色，金属度调多高都还是"塑料"。
	if bool(env_cfg.get("reflection_sky_enabled", true)):
		var sky_mat := ProceduralSkyMaterial.new()
		sky_mat.sky_top_color = _hex(env_cfg, "refl_sky_top", Color(0.62, 0.72, 0.86))
		sky_mat.sky_horizon_color = _hex(env_cfg, "refl_sky_horizon", Color(0.93, 0.95, 0.97))
		sky_mat.ground_bottom_color = _hex(env_cfg, "refl_ground", Color(0.34, 0.33, 0.31))
		sky_mat.ground_horizon_color = _hex(env_cfg, "refl_ground_horizon", Color(0.62, 0.60, 0.56))
		sky_mat.sun_angle_max = 30.0
		sky_mat.energy_multiplier = _ec(env_cfg, "refl_energy", 1.0)
		var sky := Sky.new()
		sky.sky_material = sky_mat
		e.sky = sky
		e.reflected_light_source = Environment.REFLECTION_SOURCE_SKY

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

	# 辉光：只吃超过阈值的亮部（核心水面、机关高亮），不会把整张图糊掉
	if bool(env_cfg.get("glow_enabled", true)):
		e.glow_enabled = true
		e.glow_intensity = _ec(env_cfg, "glow_intensity", 0.55)
		e.glow_bloom = _ec(env_cfg, "glow_bloom", 0.12)
		e.glow_hdr_threshold = _ec(env_cfg, "glow_hdr_threshold", 1.05)
		e.glow_hdr_scale = _ec(env_cfg, "glow_hdr_scale", 2.0)
		e.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT

	# 调色：出片前统一提一点对比和饱和
	if bool(env_cfg.get("adjust_enabled", true)):
		e.adjustment_enabled = true
		e.adjustment_brightness = _ec(env_cfg, "adjust_brightness", 1.0)
		e.adjustment_contrast = _ec(env_cfg, "adjust_contrast", 1.08)
		e.adjustment_saturation = _ec(env_cfg, "adjust_saturation", 1.12)

	# 体积雾：岛下的云用 FogVolume 来做，这里只开总开关，全局密度给 0，
	# 让密度完全由各个 FogVolume 提供。实测正交相机下工作正常。
	if bool(env_cfg.get("volumetric_enabled", true)):
		e.volumetric_fog_enabled = true
		e.volumetric_fog_density = _ec(env_cfg, "volumetric_density", 0.0)
		e.volumetric_fog_albedo = _hex(env_cfg, "volumetric_albedo", Color(1, 1, 1))
		e.volumetric_fog_length = _ec(env_cfg, "volumetric_length", 260.0)
		e.volumetric_fog_detail_spread = _ec(env_cfg, "volumetric_detail_spread", 2.0)
		e.volumetric_fog_ambient_inject = _ec(env_cfg, "volumetric_ambient_inject", 1.0)
		e.volumetric_fog_gi_inject = _ec(env_cfg, "volumetric_gi_inject", 1.0)
		e.volumetric_fog_anisotropy = _ec(env_cfg, "volumetric_anisotropy", 0.2)
		# 正交相机下时间重投影会算错，表现为云每隔几帧整片跳变一次。
		# 关掉它画面就稳了，代价是少了一点时间累积的平滑。
		e.volumetric_fog_temporal_reprojection_enabled = bool(env_cfg.get("volumetric_temporal_reprojection", false))
		e.volumetric_fog_temporal_reprojection_amount = _ec(env_cfg, "volumetric_temporal_amount", 0.9)

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
	_update_zoom_readability()
	if _backdrop != null:
		var vp := get_viewport().get_visible_rect().size
		var aspect: float = vp.x / max(vp.y, 1.0)
		_backdrop.mesh.size = Vector2(_ortho_size * aspect * 1.05, _ortho_size * 1.05)
		_backdrop.position = Vector3(0, 0, -cam.far * 0.9)
		var half_w: float = _ortho_size * aspect * 0.5
		var half_h: float = _ortho_size * 0.5
		for c in _clouds:
			var w: float = float(c.get_meta("nw")) * _ortho_size
			c.mesh.size = Vector2(w, w / float(c.get_meta("aspect")))
			c.position = Vector3(float(c.get_meta("nx")) * half_w,
				float(c.get_meta("ny")) * half_h, -cam.far * 0.86)

# ---------------------------------------------------------------- 每帧

func _process(delta: float) -> void:
	_handle_camera_pan(delta)
	_update_hover()
	_drain_fx()
	_update_camera_shake()
	hud.refresh()

## 模拟排的队，这里才真的放出来
func _drain_fx() -> void:
	if fx == null or game == null:
		return
	for e in game.fx_queue:
		fx.burst(String(e["kind"]), e["pos"], e["dir"], e["color"], float(e["power"]))
	game.fx_queue.clear()

## 抖动加在相机的局部位移上，不动 pivot，免得干扰拾取用的射线原点计算
func _update_camera_shake() -> void:
	if fx == null or cam == null:
		return
	var pitch := deg_to_rad(_pitch)
	var base := Vector3(0.0, -sin(pitch) * _dist, cos(pitch) * _dist)
	var o := fx.shake_offset()
	# 正交相机下抖动幅度要按可视范围缩放，不然拉远了等于没抖
	cam.position = base + cam.basis * (o * _ortho_size * 0.01)

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
		KEY_Z, KEY_C, KEY_V, KEY_B:
			_sandbox_spawn_key(k)
		_:
			var allowed := game.allowed_traps()
			for i in allowed.size():
				if k == KEY_1 + i and i < 9:
					select_trap(String(allowed[i]))
					break

## 拉远时敌人只有几个像素，按可视高度补偿：单位放大 + 地面标记淡入
func _update_zoom_readability() -> void:
	if game == null:
		return
	var cfg: Dictionary = Cfg.art.get("zoom_readability", {})
	if not bool(cfg.get("enabled", true)):
		game.view_unit_scale = 1.0
		game.view_marker = 0.0
		return
	var base := float(cfg.get("base_ortho", 26.0))
	var full := float(cfg.get("unit_scale_ortho", 70.0))
	var t: float = clampf((_ortho_size - base) / max(full - base, 0.001), 0.0, 1.0)
	game.view_unit_scale = lerpf(1.0, float(cfg.get("unit_scale_max", 1.7)), t)
	var ms := float(cfg.get("marker_start", 30.0))
	var mf := float(cfg.get("marker_full", 60.0))
	game.view_marker = clampf((_ortho_size - ms) / max(mf - ms, 0.001), 0.0, 1.0)
	if fx != null:
		fx.zoom_scale = lerpf(1.0, float(cfg.get("fx_scale_max", 3.0)), t)
	_update_outline_fade()

## 描边是固定像素宽的，拉远时单位只有二十来像素高，线一夹主体就糊了。
## 所以拉远时把描边淡掉 —— 那个距离上靠地面标记来保证看得见。
func _update_outline_fade() -> void:
	if _outline == null:
		return
	var env_cfg: Dictionary = Cfg.art.get("environment", {})
	var a := _ec(env_cfg, "outline_fade_start", 30.0)
	var b := _ec(env_cfg, "outline_fade_end", 52.0)
	var t: float = clampf((_ortho_size - a) / max(b - a, 0.001), 0.0, 1.0)
	var mat := _outline.material_override as ShaderMaterial
	if mat != null:
		mat.set_shader_parameter("strength", _ec(env_cfg, "outline_strength", 0.95) * (1.0 - t))

## 按地图大小自动取景：把地图四角投到相机平面，算出需要多大的正交高度
func _fit_camera_to_map() -> void:
	if game.grid == null:
		return
	var g := game.grid
	var corners := [Vector3.ZERO, Vector3(g.w * g.cell_size, 0, 0),
		Vector3(0, 0, g.h * g.cell_size), Vector3(g.w * g.cell_size, 0, g.h * g.cell_size)]
	var basis_inv := cam.global_transform.basis.inverse()
	var origin := cam.global_transform.origin
	var ex := 0.0
	var ey := 0.0
	for c in corners:
		var local: Vector3 = basis_inv * (c - origin)
		ex = max(ex, absf(local.x))
		ey = max(ey, absf(local.y))
	var vp := get_viewport().get_visible_rect().size
	var aspect: float = vp.x / max(vp.y, 1.0)
	var pad := Cfg.num("camera.fit_padding", 1.18)
	_ortho_size = clampf(max(ey * 2.0, ex * 2.0 / aspect) * pad,
		Cfg.num("camera.ortho_min", 10.0), Cfg.num("camera.ortho_max", 90.0))
	_update_camera()

## 直接指定俯角（调镜头用）。传正数，内部按俯视处理。
func set_pitch(deg: float) -> void:
	_pitch = -absf(deg)
	_update_camera()

## 直接指定正交可视高度（调美术/拍近景用）
func set_zoom(size: float) -> void:
	_ortho_size = clampf(size, Cfg.num("camera.ortho_min", 10.0), Cfg.num("camera.ortho_max", 90.0))
	_update_camera()

## 沙盒放怪：Z/C/V/B 按 enemies.json 里的顺序对应前四种敌人，加了新敌人自动有键位
const SANDBOX_KEYS := [KEY_Z, KEY_C, KEY_V, KEY_B]

func _sandbox_spawn_key(key: int) -> void:
	var ids: Array = []
	for id in Cfg.enemies.keys():
		if typeof(Cfg.enemies[id]) == TYPE_DICTIONARY:
			ids.append(String(id))
	var i := SANDBOX_KEYS.find(key)
	if i < 0 or i >= ids.size():
		return
	var data: Dictionary = Cfg.enemies[ids[i]]
	# 越大越贵的敌人放得越少
	var n: int = maxi(1, int(round(60.0 / max(float(data.get("hp", 40)), 1.0))))
	game.sandbox_spawn(ids[i], n)

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
