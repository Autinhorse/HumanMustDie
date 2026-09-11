extends Node3D
## 动作检查：把跑步的几个相位和倒地过程并排摆出来截图。
## 运行：Godot_v4.7-stable_win64.exe --path . res://tests/pose.tscn -- --shot D:/out.png

const POSES := [
	{"label": "站立", "mode": "run", "phase": 0.0, "power": 0.0},
	{"label": "跑 1/4", "mode": "run", "phase": PI * 0.5, "power": 1.0},
	{"label": "跑 3/4", "mode": "run", "phase": PI * 1.5, "power": 1.0},
	{"label": "被击飞", "mode": "tumble", "phase": 0.6, "power": 1.0},
	{"label": "倒地 40%", "mode": "death", "phase": 0.4, "power": 1.0},
	{"label": "倒地 100%", "mode": "death", "phase": 1.0, "power": 1.0},
]

func _ready() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.78, 0.83, 0.83)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.75, 0.82, 0.85)
	e.ambient_light_energy = 0.5
	env.environment = e
	add_child(env)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-45, -40, 0)
	sun.light_energy = 1.6
	sun.shadow_enabled = true
	add_child(sun)

	var spacing := 1.55
	for i in POSES.size():
		var p: Dictionary = POSES[i]
		var a := ActorView.new()
		add_child(a)
		if not a.setup("swordman", 1.0, Color(0.886, 0.290, 0.482)):
			push_error("模型载入失败")
			get_tree().quit(1)
			return
		a.position = Vector3((i - (POSES.size() - 1) / 2.0) * spacing, 0, 0)
		match String(p["mode"]):
			"run":
				a.set_run(float(p["phase"]), float(p["power"]))
			"tumble":
				a.set_tumble(float(p["phase"]))
			"death":
				a.set_death(float(p["phase"]))
				a.step_sword(float(p["phase"]) * 0.5, 24.0)
		var lab := Label3D.new()
		lab.text = String(p["label"])
		lab.font_size = 96
		lab.pixel_size = 0.0018
		lab.position = a.position + Vector3(0, -0.18, 0.4)
		lab.modulate = Color(0.15, 0.18, 0.2)
		add_child(lab)

	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	# size 是可视高度；6 个姿势横排约 9.5 宽，按 16:9 反推需要的高度
	cam.size = 5.6
	cam.position = Vector3(0, 0.62, 6.0)
	cam.rotation_degrees = Vector3(-8, 0, 0)
	add_child(cam)
	cam.current = true

	await _maybe_shot()

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
