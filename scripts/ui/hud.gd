class_name Hud
extends CanvasLayer
## 界面：状态栏、机关工具条、战斗统计面板、日志、敌人查看

var game: Game = null
var main = null

var root: Control = null
var lbl_status: Label = null
var lbl_hint: Label = null
var lbl_log: Label = null
var lbl_stats: Label = null
var lbl_banner: Label = null
var stats_panel: PanelContainer = null
var build_bar: HBoxContainer = null
var btn_wave: Button = null
var btn_pause: Button = null
var btn_sandbox: Button = null
var opt_level: OptionButton = null
var _level_ids: Array[String] = []
var speed_buttons: Array[Button] = []
var trap_buttons: Dictionary = {}

const LOG_WIDTH := 300.0

var _log_lines: PackedStringArray = PackedStringArray()
var _inspect_text: String = ""

func setup(p_game: Game, p_main) -> void:
	game = p_game
	main = p_main
	_build()
	for line in game.stats.log_lines:
		_on_log(String(line))
	game.changed.connect(refresh)
	game.logged.connect(_on_log)
	refresh()

# ---------------------------------------------------------------- 构建界面

func _build() -> void:
	root = Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.theme = _make_theme()
	add_child(root)

	# 左上：状态
	var info := _panel(Vector2(12, 12), Control.PRESET_TOP_LEFT)
	lbl_status = Label.new()
	lbl_status.custom_minimum_size = Vector2(330, 0)
	lbl_status.clip_text = true
	lbl_status.mouse_filter = Control.MOUSE_FILTER_IGNORE
	info.add_child(lbl_status)

	# 右上：控制
	var ctrl := _panel(Vector2(-12, 12), Control.PRESET_TOP_RIGHT)
	var vb := VBoxContainer.new()
	ctrl.add_child(vb)

	var row_speed := HBoxContainer.new()
	vb.add_child(row_speed)
	var speeds := Cfg.arr("sim.speeds", [0.5, 1.0, 2.0, 4.0])
	for i in speeds.size():
		var b := _button("%sx" % str(speeds[i]), func(): main.on_speed(i))
		row_speed.add_child(b)
		speed_buttons.append(b)

	var row2 := HBoxContainer.new()
	vb.add_child(row2)
	btn_pause = _button("暂停 (空格)", func(): main.on_pause())
	row2.add_child(btn_pause)
	row2.add_child(_button("重开 (F2)", func(): main.on_restart()))
	btn_sandbox = _button("沙盒 (F1)", func(): main.on_sandbox())
	row2.add_child(btn_sandbox)

	var row_level := HBoxContainer.new()
	vb.add_child(row_level)
	var lv_label := Label.new()
	lv_label.text = "关卡 "
	row_level.add_child(lv_label)
	opt_level = OptionButton.new()
	opt_level.focus_mode = Control.FOCUS_NONE
	opt_level.item_selected.connect(_on_level_selected)
	row_level.add_child(opt_level)

	var row3 := HBoxContainer.new()
	vb.add_child(row3)
	row3.add_child(_button("统计 (Tab)", func(): main.on_toggle_stats()))
	row3.add_child(_button("导出日志", func(): main.on_export_log()))
	row3.add_child(_button("重载配置 (F5)", func(): main.on_reload_config()))

	# 底部中间：机关工具条 + 开始波次
	var bottom := VBoxContainer.new()
	bottom.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	bottom.position = Vector2(0, -12)
	bottom.grow_horizontal = Control.GROW_DIRECTION_BOTH
	bottom.grow_vertical = Control.GROW_DIRECTION_BEGIN
	bottom.alignment = BoxContainer.ALIGNMENT_CENTER
	root.add_child(bottom)

	lbl_hint = Label.new()
	lbl_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	bottom.add_child(lbl_hint)

	var bar_panel := PanelContainer.new()
	bottom.add_child(bar_panel)
	build_bar = HBoxContainer.new()
	bar_panel.add_child(build_bar)

	var wave_row := HBoxContainer.new()
	wave_row.alignment = BoxContainer.ALIGNMENT_CENTER
	bottom.add_child(wave_row)
	btn_wave = _button("开始下一波 (Enter)", func(): main.on_start_wave())
	wave_row.add_child(btn_wave)

	# 左下：日志
	var log_panel := _panel(Vector2(12, -12), Control.PRESET_BOTTOM_LEFT)
	lbl_log = Label.new()
	lbl_log.custom_minimum_size = Vector2(LOG_WIDTH, 150)
	lbl_log.clip_text = true          # 长行截断，不让面板被撑宽
	lbl_log.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl_log.vertical_alignment = VERTICAL_ALIGNMENT_BOTTOM
	log_panel.add_child(lbl_log)

	# 右侧：统计面板
	stats_panel = _panel(Vector2(-12, 200), Control.PRESET_TOP_RIGHT)
	lbl_stats = Label.new()
	lbl_stats.custom_minimum_size = Vector2(420, 0)
	lbl_stats.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lbl_stats.add_theme_font_override("font", _mono_font())
	lbl_stats.add_theme_font_size_override("font_size", 13)
	stats_panel.add_child(lbl_stats)
	stats_panel.visible = false

	# 中间：横幅
	lbl_banner = Label.new()
	lbl_banner.set_anchors_preset(Control.PRESET_CENTER)
	lbl_banner.grow_horizontal = Control.GROW_DIRECTION_BOTH
	lbl_banner.grow_vertical = Control.GROW_DIRECTION_BOTH
	lbl_banner.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	lbl_banner.add_theme_font_size_override("font_size", 34)
	lbl_banner.visible = false
	root.add_child(lbl_banner)

	rebuild_build_bar()
	rebuild_level_list()

func rebuild_level_list() -> void:
	if opt_level == null or game == null:
		return
	_level_ids.clear()
	opt_level.clear()
	var ids := Cfg.levels.keys()
	ids.sort()
	for id in ids:
		var lv: Dictionary = Cfg.levels[id]
		_level_ids.append(String(id))
		opt_level.add_item(String(lv.get("name", id)))
		if String(id) == game.level_id:
			opt_level.select(_level_ids.size() - 1)

func _on_level_selected(index: int) -> void:
	if index >= 0 and index < _level_ids.size() and main != null:
		main.switch_level(_level_ids[index])

func rebuild_build_bar() -> void:
	for c in build_bar.get_children():
		build_bar.remove_child(c)
		c.queue_free()
	trap_buttons.clear()
	var i := 0
	for id in game.allowed_traps():
		i += 1
		var data: Dictionary = Cfg.traps.get(id, {})
		var label := "%d  %s\n%d 金" % [i, String(data.get("name", id)), int(Cfg.dget(data, "cost", 0.0))]
		var tid := String(id)
		var b := _button(label, func(): main.select_trap(tid))
		b.tooltip_text = String(data.get("desc", ""))
		b.custom_minimum_size = Vector2(96, 46)
		build_bar.add_child(b)
		trap_buttons[tid] = b

func _panel(offset: Vector2, preset: int) -> PanelContainer:
	var p := PanelContainer.new()
	p.set_anchors_preset(preset)
	p.position = offset
	# 信息面板只是显示，不能吃掉点击 —— 否则窗口一窄就会盖住机关按钮按不动
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	match preset:
		Control.PRESET_TOP_RIGHT:
			p.grow_horizontal = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_BOTTOM_LEFT:
			p.grow_vertical = Control.GROW_DIRECTION_BEGIN
	root.add_child(p)
	return p

func _button(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE
	b.pressed.connect(cb)
	return b

func _make_theme() -> Theme:
	var t := Theme.new()
	var f := SystemFont.new()
	f.font_names = PackedStringArray(["Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "Sans-Serif"])
	t.default_font = f
	t.default_font_size = 15
	return t

func _mono_font() -> SystemFont:
	var f := SystemFont.new()
	f.font_names = PackedStringArray(["Consolas", "Microsoft YaHei Mono", "Microsoft YaHei", "monospace"])
	return f

# ---------------------------------------------------------------- 刷新

func refresh() -> void:
	if game == null:
		return
	if game.load_error != "":
		lbl_banner.visible = true
		lbl_banner.text = "配置错误：\n" + game.load_error
		lbl_status.text = game.load_error
		return

	var phase_name: String = String(Game.PHASE_NAMES.get(game.phase, "?"))
	var lines: Array[String] = []
	lines.append("阶段：%s%s" % [phase_name, "（暂停）" if game.paused else ""])
	lines.append("波次：%d / %d   %s" % [max(game.wave_index + 1, 0), game.wave_count(), game.current_wave_name()])
	lines.append("核心生命：%d      金币：%d" % [game.core_hp, game.gold])
	lines.append("场上敌人：%d      速度：%sx" % [game.enemies.size(), str(game.sim_speed)])
	lines.append("下一波：%s" % game.next_wave_summary())
	lines.append("种子：%d%s" % [game.seed_value, "   [沙盒模式]" if game.sandbox else ""])
	lines.append("版本：v%s" % str(ProjectSettings.get_setting("application/config/version", "0.0.0")))
	if _inspect_text != "":
		lines.append("")
		lines.append("选中：" + _inspect_text)
	lbl_status.text = "\n".join(lines)

	btn_pause.text = "继续 (空格)" if game.paused else "暂停 (空格)"
	btn_sandbox.text = "沙盒：开 (F1)" if game.sandbox else "沙盒：关 (F1)"
	btn_wave.disabled = game.phase != Game.Phase.BUILD
	for i in speed_buttons.size():
		speed_buttons[i].modulate = Color(1, 1, 0.4) if i == game.speed_index else Color(1, 1, 1)

	for id in trap_buttons.keys():
		var cost := int(Cfg.dget(Cfg.traps.get(id, {}), "cost", 0.0))
		var affordable: bool = game.sandbox or game.gold >= cost
		var usable: bool = affordable and (game.phase == Game.Phase.BUILD or game.sandbox)
		trap_buttons[id].modulate = Color(1, 1, 1) if usable else Color(0.55, 0.55, 0.55)
		trap_buttons[id].button_pressed = false

	if main != null and main.pending_trap_id != "":
		var tn := String(Cfg.traps.get(main.pending_trap_id, {}).get("name", main.pending_trap_id))
		if trap_buttons.has(main.pending_trap_id):
			trap_buttons[main.pending_trap_id].modulate = Color(1, 0.9, 0.3)
		lbl_hint.text = "放置【%s】：左键放置，R 旋转朝向，右键/ESC 取消%s" % [tn, main.place_error_text]
	else:
		lbl_hint.text = "1-5 选择机关   左键选中已放置机关（X 拆除）   Q/E 转视角   WASD 平移   滚轮缩放"

	if stats_panel.visible:
		lbl_stats.text = "\n".join(game.stats.report_lines(game.trap_names()))

	if game.phase == Game.Phase.WIN:
		lbl_banner.visible = true
		lbl_banner.text = "胜利！守住了全部 %d 波\n按 F2 重开" % game.wave_count()
	elif game.phase == Game.Phase.LOSE:
		lbl_banner.visible = true
		lbl_banner.text = "核心被摧毁\n按 F2 重开"
	else:
		lbl_banner.visible = false

func toggle_stats() -> void:
	stats_panel.visible = not stats_panel.visible
	refresh()

func set_inspect(text: String) -> void:
	_inspect_text = text
	refresh()

func _on_log(line: String) -> void:
	_log_lines.append(line)
	while _log_lines.size() > 9:
		_log_lines.remove_at(0)
	lbl_log.text = "\n".join(_log_lines)
