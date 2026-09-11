class_name HGrid
extends RefCounted
## 逻辑网格：只管格子类型与坐标换算，和视觉模型完全分离（文档 15.3）

enum Cell { VOID = 0, FLOOR = 1, WALL = 2, OBSTACLE = 3, BRIDGE = 4, CORE = 5 }

const CELL_NAMES := {
	Cell.VOID: "空地",
	Cell.FLOOR: "普通地面",
	Cell.WALL: "墙",
	Cell.OBSTACLE: "障碍",
	Cell.BRIDGE: "桥面",
	Cell.CORE: "目标核心",
}

const DIRS: Array[Vector2i] = [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]

var w: int = 0
var h: int = 0
var cell_size: float = 2.0
var _cells: PackedInt32Array = PackedInt32Array()

func load_rows(rows: Array, p_cell_size: float) -> String:
	cell_size = p_cell_size
	h = rows.size()
	if h == 0:
		return "地图为空"
	w = String(rows[0]).length()
	_cells = PackedInt32Array()
	_cells.resize(w * h)
	for y in h:
		var line := String(rows[y])
		if line.length() != w:
			return "第 %d 行长度 %d 与首行 %d 不一致" % [y, line.length(), w]
		for x in w:
			var c := line[x]
			if not c.is_valid_int():
				return "第 %d 行第 %d 列不是合法格子类型: %s" % [y, x, c]
			var v := int(c)
			if v < 0 or v > 5:
				return "第 %d 行第 %d 列格子类型越界: %d" % [y, x, v]
			_cells[y * w + x] = v
	return ""

func in_bounds(c: Vector2i) -> bool:
	return c.x >= 0 and c.y >= 0 and c.x < w and c.y < h

func get_cell(c: Vector2i) -> int:
	if not in_bounds(c):
		return Cell.VOID
	return _cells[c.y * w + c.x]

func set_cell(c: Vector2i, v: int) -> void:
	if in_bounds(c):
		_cells[c.y * w + c.x] = v

## 敌人只能走普通地面、桥面和核心（文档 5.3）
func is_walkable(c: Vector2i) -> bool:
	var t := get_cell(c)
	return t == Cell.FLOOR or t == Cell.BRIDGE or t == Cell.CORE

func is_wall(c: Vector2i) -> bool:
	return get_cell(c) == Cell.WALL

func has_ground(c: Vector2i) -> bool:
	## 有没有可以站住的地面。空地下面是镂空的，被推过去就会掉下去。
	return is_walkable(c) or get_cell(c) == Cell.OBSTACLE

func cell_center(c: Vector2i) -> Vector3:
	return Vector3((float(c.x) + 0.5) * cell_size, 0.0, (float(c.y) + 0.5) * cell_size)

func world_to_cell(p: Vector3) -> Vector2i:
	return Vector2i(int(floor(p.x / cell_size)), int(floor(p.z / cell_size)))

func center_world() -> Vector3:
	return Vector3(float(w) * cell_size * 0.5, 0.0, float(h) * cell_size * 0.5)

func cells_of_type(t: int) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	for y in h:
		for x in w:
			if _cells[y * w + x] == t:
				out.append(Vector2i(x, y))
	return out

func is_border(c: Vector2i) -> bool:
	return c.x == 0 or c.y == 0 or c.x == w - 1 or c.y == h - 1

## 墙面的某一面能否放机关：按设计确认——只有朝向另一面墙的那一面被挡住，
## 其余暴露的面（含朝向障碍、空地的面）都可以放置。
func wall_face_free(c: Vector2i, dir: Vector2i) -> bool:
	if not is_wall(c):
		return false
	var n := c + dir
	if not in_bounds(n):
		return false
	return not is_wall(n)

func exposed_faces(c: Vector2i) -> Array[Vector2i]:
	var out: Array[Vector2i] = []
	for d in DIRS:
		if wall_face_free(c, d):
			out.append(d)
	return out
