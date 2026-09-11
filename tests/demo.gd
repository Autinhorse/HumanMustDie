extends Node
## 演示场景：自动搭好一套"聚怪—推下桥—锯墙处决"的杀戮区并开打，用来快速看连锁效果。
## 运行：Godot_v4.7-stable_win64.exe --path . res://tests/demo.tscn
## 调美术时自动出图：... res://tests/demo.tscn -- --shot C:/path/out.png [--shot-delay 6]

func _ready() -> void:
	var m = load("res://scenes/main.tscn").instantiate()
	add_child(m)
	await get_tree().process_frame
	var g: Game = m.game
	if g.load_error != "":
		return
	g.gold = 99999
	g.place("tar", Vector2i(6, 11), Vector2i(0, -1))
	g.place("tar", Vector2i(7, 11), Vector2i(0, -1))
	g.place("spikes", Vector2i(6, 12), Vector2i(0, -1))
	g.place("spikes", Vector2i(7, 12), Vector2i(0, -1))
	g.place("push_wall", Vector2i(5, 9), Vector2i(1, 0))
	g.place("saw", Vector2i(8, 9), Vector2i(-1, 0))
	g.place("launcher", Vector2i(6, 14), Vector2i(0, -1))
	g.gold = Cfg.int_at("economy.start_gold", 320)
	m.hud.toggle_stats()
	g.start_wave()
	await _maybe_screenshot()

## 给美术调参用：等几秒让战斗铺开，截一张图存盘然后退出
func _maybe_screenshot() -> void:
	var args := OS.get_cmdline_user_args()
	var path := ""
	var delay := 6.0
	var ortho := 0.0
	var pitch := 0.0
	for i in args.size():
		if args[i] == "--shot" and i + 1 < args.size():
			path = args[i + 1]
		elif args[i] == "--shot-delay" and i + 1 < args.size():
			delay = float(args[i + 1])
		elif args[i] == "--ortho" and i + 1 < args.size():
			ortho = float(args[i + 1])
		elif args[i] == "--pitch" and i + 1 < args.size():
			pitch = float(args[i + 1])
	if path == "":
		return
	var m := get_child(0)
	if ortho > 0.0:
		m.set_zoom(ortho)
	if pitch > 0.0:
		m.set_pitch(pitch)
	await get_tree().create_timer(delay).timeout
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(path)
	print("SHOT_SAVED %s (err=%d)" % [path, err])
	get_tree().quit(0 if err == OK else 1)
