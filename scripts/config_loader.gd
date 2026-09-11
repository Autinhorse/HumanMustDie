extends Node
## 全局配置加载器（Autoload 名: Cfg）
## 所有数值都来自 res://data/ 下的 JSON；导出后可用 user://data/ 同名文件覆盖，便于策划改数值。

const DATA_DIR := "res://data/"
const OVERRIDE_DIR := "user://data/"

var config: Dictionary = {}
var enemies: Dictionary = {}
var traps: Dictionary = {}
var levels: Dictionary = {}
var errors: PackedStringArray = []

func _ready() -> void:
	load_all()

func load_all() -> void:
	errors = PackedStringArray()
	config = _load_json("config.json")
	enemies = _load_json("enemies.json")
	traps = _load_json("traps.json")
	levels = {}
	for lv in _list_levels():
		var d := _load_json("levels/%s.json" % lv)
		if not d.is_empty():
			levels[lv] = d
	if errors.size() > 0:
		for e in errors:
			push_error(e)

func _list_levels() -> PackedStringArray:
	var out := PackedStringArray()
	var dir := DirAccess.open(DATA_DIR + "levels")
	if dir != null:
		for f in dir.get_files():
			if f.ends_with(".json"):
				out.append(f.get_basename())
			elif f.ends_with(".json.remap"): # 导出后资源会被 remap
				out.append(f.get_basename().get_basename())
	if out.is_empty():
		out.append("corridor_01")
	return out

func _load_json(rel: String) -> Dictionary:
	var path := DATA_DIR + rel
	if FileAccess.file_exists(OVERRIDE_DIR + rel):
		path = OVERRIDE_DIR + rel
	elif not FileAccess.file_exists(path):
		errors.append("缺少配置文件: %s" % path)
		return {}
	var text := FileAccess.get_file_as_string(path)
	var json := JSON.new()
	if json.parse(text) != OK:
		errors.append("%s 第 %d 行 JSON 解析失败: %s" % [path, json.get_error_line(), json.get_error_message()])
		return {}
	if typeof(json.data) != TYPE_DICTIONARY:
		errors.append("%s 根节点必须是 JSON 对象" % path)
		return {}
	return json.data

## 点号路径取值，例如 Cfg.num("combat.gravity", 24.0)
func num(path: String, def: float = 0.0) -> float:
	var v: Variant = _dig(path)
	if v == null:
		return def
	if typeof(v) == TYPE_FLOAT or typeof(v) == TYPE_INT:
		return float(v)
	return def

func int_at(path: String, def: int = 0) -> int:
	return int(num(path, float(def)))

func arr(path: String, def: Array = []) -> Array:
	var v: Variant = _dig(path)
	if typeof(v) == TYPE_ARRAY:
		return v
	return def

func dict(path: String, def: Dictionary = {}) -> Dictionary:
	var v: Variant = _dig(path)
	if typeof(v) == TYPE_DICTIONARY:
		return v
	return def

func str_at(path: String, def: String = "") -> String:
	var v: Variant = _dig(path)
	if typeof(v) == TYPE_STRING:
		return v
	return def

func _dig(path: String) -> Variant:
	var cur: Variant = config
	for part in path.split("."):
		if typeof(cur) != TYPE_DICTIONARY or not cur.has(part):
			return null
		cur = cur[part]
	return cur

## 工具：JSON 里的 [r,g,b] 转 Color
static func to_color(v: Variant, def: Color = Color.MAGENTA) -> Color:
	if typeof(v) == TYPE_ARRAY and v.size() >= 3:
		return Color(float(v[0]), float(v[1]), float(v[2]))
	return def

static func dget(d: Dictionary, key: String, def: float) -> float:
	if d.has(key):
		return float(d[key])
	return def
