class_name RunStats
extends RefCounted
## 战斗数据记录（文档 18）。面板实时显示，也可导出成文本日志。

var per_trap: Dictionary = {}          # trap_id -> {damage, kills, control, displacements, combo_kills}
var kills_total: int = 0
var kills_by_cause: Dictionary = {}    # kill / fall / collision / core
var damage_total: float = 0.0
var fall_entered: int = 0
var leaks: int = 0
var wave_times: Array = []             # [{wave, prep, combat}]
var prep_timer: float = 0.0
var combat_timer: float = 0.0
var log_lines: PackedStringArray = PackedStringArray()

func _slot(id: String) -> Dictionary:
	if not per_trap.has(id):
		per_trap[id] = {"damage": 0.0, "kills": 0, "control": 0.0, "displacements": 0, "combo_kills": 0}
	return per_trap[id]

func add_damage(source: String, amount: float) -> void:
	if amount <= 0.0:
		return
	damage_total += amount
	if source.begins_with("trap:"):
		_slot(source.substr(5))["damage"] += amount

func add_control(source: String, seconds: float) -> void:
	if source.begins_with("trap:"):
		_slot(source.substr(5))["control"] += seconds

func add_displacement(source: String) -> void:
	if source.begins_with("trap:"):
		_slot(source.substr(5))["displacements"] += 1

func add_fall_entered() -> void:
	fall_entered += 1

func add_kill(cause: String, source: String, combo: bool) -> void:
	kills_total += 1
	kills_by_cause[cause] = int(kills_by_cause.get(cause, 0)) + 1
	if source.begins_with("trap:"):
		var s := _slot(source.substr(5))
		s["kills"] += 1
		if combo:
			s["combo_kills"] += 1

func add_leak() -> void:
	leaks += 1

func close_wave(wave_index: int) -> void:
	wave_times.append({"wave": wave_index + 1, "prep": prep_timer, "combat": combat_timer})
	prep_timer = 0.0
	combat_timer = 0.0

func add_log(line: String) -> void:
	log_lines.append(line)
	if log_lines.size() > 400:
		log_lines.remove_at(0)

func fall_ratio() -> float:
	if kills_total == 0:
		return 0.0
	return float(kills_by_cause.get("fall", 0)) / float(kills_total)

func report_lines(trap_names: Dictionary) -> PackedStringArray:
	var out := PackedStringArray()
	out.append("总击杀 %d   总伤害 %d   漏怪 %d" % [kills_total, int(damage_total), leaks])
	var fall := int(kills_by_cause.get("fall", 0))
	var coll := int(kills_by_cause.get("collision", 0))
	out.append("坠落击杀 %d (%.0f%%)   撞击击杀 %d   进坑次数 %d" % [fall, fall_ratio() * 100.0, coll, fall_entered])
	out.append("")
	out.append("%-8s %8s %6s %8s %6s %6s" % ["机关", "伤害", "击杀", "控制秒", "位移", "连锁"])
	for id in per_trap.keys():
		var s: Dictionary = per_trap[id]
		out.append("%-8s %8d %6d %8.1f %6d %6d" % [
			String(trap_names.get(id, id)), int(s["damage"]), int(s["kills"]),
			float(s["control"]), int(s["displacements"]), int(s["combo_kills"])])
	if not wave_times.is_empty():
		out.append("")
		out.append("波次用时（准备 / 战斗）")
		for w in wave_times:
			out.append("  第%d波  %.0fs / %.0fs" % [int(w["wave"]), float(w["prep"]), float(w["combat"])])
	return out

func to_text(trap_names: Dictionary) -> String:
	var out := "=== 战斗统计 ===\n"
	out += "\n".join(report_lines(trap_names))
	out += "\n\n=== 战斗日志 ===\n"
	out += "\n".join(log_lines)
	return out
