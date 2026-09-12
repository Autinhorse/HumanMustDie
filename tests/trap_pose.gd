extends Node3D
## 机关模型检查：五种机关并排，上排静止、下排触发中，按游戏里的格子尺寸和相机角度摆。
## 运行：Godot_v4.7-stable_win64.exe --path . res://tests/trap_pose.tscn -- --shot D:/out.png
##
## 可选：--fire 0.1   下排停在触发后第几秒（默认取 attack 结束、动作最大的那一刻）
##       --ortho 9    正交相机可视高度
##       --actor      顺便摆一个小兵当比例尺

const ORDER := ["spikes", "tar", "launcher", "push_wall", "saw"]

func _ready() -> void:
	var cs: float = float(Cfg.config.get("grid", {}).get("cell_size", 2.0))
	# wall_height 在配置里**已经是世界单位**（board_view 直接拿它当高度用），
	# 不要再乘 cell_size —— 乘了的话检查场景的墙比游戏里高一倍，
	# 墙面机关看着就永远对不上。
	var wall_h: float = float(Cfg.config.get("grid", {}).get("wall_height", 1.0))
	_world(cs)

	var spacing := cs * 1.6
	for i in ORDER.size():
		var id: String = ORDER[i]
		var d: Dictionary = Cfg.traps[id]
		var anim: Dictionary = d.get("anim", {})
		var x := (i - (ORDER.size() - 1) / 2.0) * spacing
		var is_wall := String(d.get("mount", "ground")) == "wall"

		for row in 2:
			var z := (row - 0.5) * spacing * 1.5
			if is_wall:
				# 墙面机关要有墙才看得出关系：墙在 +Z 侧，机关朝 -Z 伸出
				var w := MeshInstance3D.new()
				var bm := BoxMesh.new()
				bm.size = Vector3(cs, wall_h, cs)
				w.mesh = bm
				var wm := StandardMaterial3D.new()
				wm.albedo_color = Color(0.80, 0.79, 0.75)
				w.material_override = wm
				w.position = Vector3(x, wall_h * 0.5, z + cs * 0.5)
				add_child(w)

			var v := TrapView.new()
			add_child(v)
			if not v.setup(TrapView.model_for(d), cs, Cfg.to_color(d.get("color"), Color.GRAY), anim):
				push_error("机关模型载入失败：" + id)
				get_tree().quit(1)
				return
			v.position = Vector3(x, 0, z)
			if row == 1:
				# 下排：停在动作幅度最大的那一帧
				v.fire()
				v.step(_fire_time(anim))
			else:
				v.step(0.0)
			v.set_process(false)          # 静帧，别让待机动作在截图前跑掉

		var lab := Label3D.new()
		lab.text = String(d.get("name", id))
		lab.rotation_degrees.y = 180.0
		lab.font_size = 96
		lab.pixel_size = 0.0022
		lab.position = Vector3(x, 0.02, -spacing * 1.35)
		lab.modulate = Color(0.16, 0.19, 0.22)
		add_child(lab)

	if "--actor" in OS.get_cmdline_user_args():
		var a := ActorView.new()
		add_child(a)
		a.setup("swordman", float(Cfg.enemies.get("grunt", {}).get("height", 1.0)),
			Cfg.to_color(Cfg.enemies.get("grunt", {}).get("color"), Color(0.886, 0.29, 0.482)))
		a.position = Vector3(-(ORDER.size() / 2.0 + 0.6) * spacing, 0, 0)
		a.set_run(PI * 0.5, 1.0)

	_camera(spacing)
	await _maybe_shot()

## 动作最大的时刻：attack 走完、hold 还没结束。spin/bob 没有这个概念，给个固定值
func _fire_time(anim: Dictionary) -> float:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--fire" and i + 1 < args.size():
			return float(args[i + 1])
	var kind := String(anim.get("type", ""))
	if kind == "spin":
		return 0.11         # 转一个不对称的角度，看得出锯齿
	if kind == "bob":
		return 1.0
	return float(anim.get("attack", 0.06)) + float(anim.get("hold", 0.12)) * 0.5

func _world(cs: float) -> void:
	# 光照直接读 art.json 的 environment —— 检查场景要是自己配一套光，
	# 出来的图就不代表游戏，调半天是白调的（之前就是这么坑过一次）。
	var ec: Dictionary = Cfg.art.get("environment", {})
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.78, 0.83, 0.83)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Cfg.to_color(ec.get("ambient_color"), Color(0.65, 0.70, 0.78))
	e.ambient_light_energy = float(ec.get("ambient_energy", 0.36))
	e.ssao_enabled = bool(ec.get("ssao_enabled", true))
	e.ssao_radius = float(ec.get("ssao_radius", 1.0))
	e.ssao_intensity = float(ec.get("ssao_intensity", 2.6))
	e.ssao_power = float(ec.get("ssao_power", 2.0))
	# 和 main.gd 一样挂一个只给反射用的天空，否则这里的金属件看起来和游戏里不一样
	if bool(ec.get("reflection_sky_enabled", true)):
		var sky_mat := ProceduralSkyMaterial.new()
		sky_mat.sky_top_color = Cfg.to_color(ec.get("refl_sky_top"), Color(0.62, 0.72, 0.86))
		sky_mat.sky_horizon_color = Cfg.to_color(ec.get("refl_sky_horizon"), Color(0.93, 0.95, 0.97))
		sky_mat.ground_bottom_color = Cfg.to_color(ec.get("refl_ground"), Color(0.34, 0.33, 0.31))
		sky_mat.ground_horizon_color = Cfg.to_color(ec.get("refl_ground_horizon"), Color(0.62, 0.60, 0.56))
		sky_mat.energy_multiplier = float(ec.get("refl_energy", 1.0))
		var sky := Sky.new()
		sky.sky_material = sky_mat
		# 背景不是天空时，Godot 默认不一定会去生成天空的辐照度贴图，
		# 强制成实时处理才拿得到反射
		sky.process_mode = Sky.PROCESS_MODE_REALTIME
		sky.radiance_size = Sky.RADIANCE_SIZE_128
		e.sky = sky
		e.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	env.environment = e
	add_child(env)

	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(-deg_to_rad(float(ec.get("sun_elevation_deg", 42.0))),
		deg_to_rad(float(ec.get("sun_azimuth_deg", 35.0))), 0.0)
	sun.light_color = Cfg.to_color(ec.get("sun_color"), Color(1.0, 0.96, 0.91))
	sun.light_energy = float(ec.get("sun_energy", 0.92))
	sun.shadow_enabled = true
	add_child(sun)

	var ground := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(cs * 20.0, cs * 20.0)
	ground.mesh = pm
	var gm := StandardMaterial3D.new()
	gm.albedo_color = Color(0.90, 0.88, 0.84)
	ground.material_override = gm
	ground.position.y = -0.001      # 压一点，免得和机关底座 z-fighting
	add_child(ground)

func _camera(spacing: float) -> void:
	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.size = spacing * 3.0
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--ortho" and i + 1 < args.size():
			cam.size = float(args[i + 1])
	# 用游戏里的俯角（45°）和一点偏航，才是玩家真正看到的样子
	var pivot := Vector3(0, 0.2, 0)
	var elev := deg_to_rad(45.0)
	var yaw := deg_to_rad(200.0)
	cam.position = pivot + Vector3(cos(elev) * sin(yaw), sin(elev), cos(elev) * cos(yaw)) * 30.0
	add_child(cam)
	cam.look_at(pivot, Vector3.UP)
	cam.current = true

func _maybe_shot() -> void:
	var args := OS.get_cmdline_user_args()
	var path := ""
	for i in args.size():
		if args[i] == "--shot" and i + 1 < args.size():
			path = args[i + 1]
	if path == "":
		return
	await get_tree().create_timer(0.6).timeout
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	print("SHOT_SAVED %s (err=%d)" % [path, img.save_png(path)])
	get_tree().quit(0)
