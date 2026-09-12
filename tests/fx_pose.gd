extends Node3D
## 打击特效检查：五种效果并排各放一发，在生命周期中段截图。
## 战斗里特效什么时候出现全看运气，连拍很难抓到，这里是确定性的。
##
## 运行：Godot_v4.7-stable_win64.exe --path . res://tests/fx_pose.tscn -- --shot D:/out.png
## 可选：--at 0.18   在触发后第几秒截图（默认 0.18，粒子飞开但还没消失）

const KINDS := [
	{"kind": "hit", "label": "受击火花", "dir": Vector3(1, 0, 0), "color": Color(0.82, 0.26, 0.24)},
	{"kind": "launch", "label": "击飞", "dir": Vector3(0.6, 0.8, 0), "color": Color(0.88, 0.62, 0.2)},
	{"kind": "land", "label": "落地扬尘", "dir": Vector3.ZERO, "color": Color(0.82, 0.79, 0.72)},
	{"kind": "death", "label": "死亡爆散", "dir": Vector3.ZERO, "color": Color(0.886, 0.29, 0.482)},
	{"kind": "fall", "label": "坠坑", "dir": Vector3.DOWN, "color": Color(0.82, 0.79, 0.72)},
]

func _ready() -> void:
	_world()
	var fx := Fx.new()
	fx.setup(Cfg.art.get("fx", {}))
	add_child(fx)
	# 和 main.gd 用同一条曲线，不然这里调好的大小到游戏里又不对了
	var zr: Dictionary = Cfg.art.get("zoom_readability", {})
	var base := float(zr.get("base_ortho", 26.0))
	var full := float(zr.get("unit_scale_ortho", 70.0))
	var t: float = clampf((_ortho() - base) / max(full - base, 0.001), 0.0, 1.0)
	fx.zoom_scale = lerpf(1.0, float(zr.get("fx_scale_max", 3.0)), t)

	# 间距跟着相机可视范围走：游戏里是 ortho 46，只有按真实尺度看才知道粒子够不够大
	var spacing: float = _ortho() / 2.6
	for i in KINDS.size():
		var k: Dictionary = KINDS[i]
		var x := (i - (KINDS.size() - 1) / 2.0) * spacing
		var lab := Label3D.new()
		lab.text = String(k["label"])
		lab.rotation_degrees.y = 180.0
		lab.font_size = 80
		lab.pixel_size = 0.0030 * spacing / 3.0
		lab.position = Vector3(x, 0.05, -spacing * 0.7)
		lab.modulate = Color(0.16, 0.19, 0.22)
		add_child(lab)
		fx.burst(String(k["kind"]), Vector3(x, 0.9, 0), k["dir"], k["color"], 1.0)

	_camera(spacing)
	await _maybe_shot()

func _world() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.80, 0.84, 0.85)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.75, 0.82, 0.85)
	e.ambient_light_energy = 0.5
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 150, 0)
	sun.light_energy = 1.4
	add_child(sun)
	var ground := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(60, 60)
	ground.mesh = pm
	var gm := StandardMaterial3D.new()
	gm.albedo_color = Color(0.90, 0.88, 0.84)
	ground.material_override = gm
	add_child(ground)

func _ortho() -> float:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--ortho" and i + 1 < args.size():
			return float(args[i + 1])
	return 7.8

func _camera(spacing: float) -> void:
	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.size = _ortho()
	var pivot := Vector3(0, 0.8, 0)
	var elev := deg_to_rad(28.0)
	var yaw := deg_to_rad(180.0)
	cam.position = pivot + Vector3(cos(elev) * sin(yaw), sin(elev), cos(elev) * cos(yaw)) * 30.0
	add_child(cam)
	cam.look_at(pivot, Vector3.UP)
	cam.current = true

func _maybe_shot() -> void:
	var args := OS.get_cmdline_user_args()
	var path := ""
	var at := 0.18
	for i in args.size():
		if args[i] == "--shot" and i + 1 < args.size():
			path = args[i + 1]
		elif args[i] == "--at" and i + 1 < args.size():
			at = float(args[i + 1])
	if path == "":
		return
	await get_tree().create_timer(at).timeout
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	print("SHOT_SAVED %s (err=%d)" % [path, img.save_png(path)])
	get_tree().quit(0)
