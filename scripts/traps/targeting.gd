class_name TrapTargeting
extends RefCounted
## 机关五段组件之一：目标选择。放置时算一次覆盖格，供触发判定和覆盖范围预览共用。

static func compute(params: Dictionary, cell: Vector2i, facing: Vector2i, grid: HGrid) -> Array[Vector2i]:
	var t := String(params.get("type", "self_cell"))
	match t:
		"self_cell":
			return [cell] as Array[Vector2i]
		"front_box":
			return _front_box(params, cell, facing, grid)
		"radius":
			return _radius(params, cell, grid)
		_:
			push_warning("未知 targeting 类型: %s" % t)
			return [cell] as Array[Vector2i]

static func _front_box(params: Dictionary, cell: Vector2i, facing: Vector2i, grid: HGrid) -> Array[Vector2i]:
	var length := int(params.get("length", 1))
	var width := int(params.get("width", 1))
	var side := Vector2i(-facing.y, facing.x)
	var half := int(floor(float(width - 1) / 2.0))
	var out: Array[Vector2i] = []
	for i in range(1, length + 1):
		var base: Vector2i = cell + facing * i
		for j in range(-half, width - half):
			var c: Vector2i = base + side * j
			if grid.in_bounds(c) and not grid.is_wall(c) and grid.get_cell(c) != HGrid.Cell.OBSTACLE:
				out.append(c)
	return out

static func _radius(params: Dictionary, cell: Vector2i, grid: HGrid) -> Array[Vector2i]:
	var r := int(params.get("r", 1))
	var out: Array[Vector2i] = []
	for dy in range(-r, r + 1):
		for dx in range(-r, r + 1):
			var c := cell + Vector2i(dx, dy)
			if grid.in_bounds(c) and not grid.is_wall(c):
				out.append(c)
	return out
