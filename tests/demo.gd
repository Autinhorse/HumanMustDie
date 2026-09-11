extends Node
## 演示场景：自动搭好一套"聚怪—推下桥—锯墙处决"的杀戮区并开打，用来快速看连锁效果。
## 运行：Godot_v4.7-stable_win64.exe --path . res://tests/demo.tscn

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
