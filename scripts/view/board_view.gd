class_name BoardView
extends Node3D
## 灰盒地图表现。逻辑网格与视觉模型分离：这里只负责按格子类型摆占位方块。

var grid: HGrid = null
var _mats: Dictionary = {}

const COLORS := {
	HGrid.Cell.FLOOR: Color(0.42, 0.44, 0.48),
	HGrid.Cell.BRIDGE: Color(0.50, 0.42, 0.30),
	HGrid.Cell.WALL: Color(0.26, 0.28, 0.34),
	HGrid.Cell.OBSTACLE: Color(0.20, 0.21, 0.24),
	HGrid.Cell.CORE: Color(0.25, 0.75, 0.95),
}

func build(p_grid: HGrid, entrance_cells: Array) -> void:
	grid = p_grid
	for c in get_children():
		remove_child(c)
		c.queue_free()
	_mats.clear()

	var cs := grid.cell_size
	var gap := Cfg.num("grid.cell_gap", 0.06)
	var thick := Cfg.num("grid.floor_thickness", 0.25)
	var support := Cfg.num("grid.support_depth", 1.8)
	var wall_h := Cfg.num("grid.wall_height", 1.0)

	for y in grid.h:
		for x in grid.w:
			var cell := Vector2i(x, y)
			var t := grid.get_cell(cell)
			var center := grid.cell_center(cell)
			match t:
				HGrid.Cell.VOID:
					pass
				HGrid.Cell.FLOOR:
					_box(center + Vector3(0, -thick * 0.5, 0), Vector3(cs - gap, thick, cs - gap), COLORS[t])
					_box(center + Vector3(0, -thick - support * 0.5, 0),
						Vector3(cs * 0.7, support, cs * 0.7), COLORS[t].darkened(0.55))
				HGrid.Cell.BRIDGE:
					_box(center + Vector3(0, -thick * 0.4, 0), Vector3(cs - gap, thick * 0.8, cs - gap), COLORS[t])
				HGrid.Cell.WALL:
					_box(center + Vector3(0, wall_h * 0.5, 0), Vector3(cs - gap * 0.5, wall_h, cs - gap * 0.5), COLORS[t])
					_box(center + Vector3(0, -thick * 0.5, 0), Vector3(cs - gap, thick, cs - gap), COLORS[HGrid.Cell.FLOOR].darkened(0.2))
				HGrid.Cell.OBSTACLE:
					_box(center + Vector3(0, wall_h * 0.7, 0), Vector3(cs * 0.8, wall_h * 1.4, cs * 0.8), COLORS[t])
					_box(center + Vector3(0, -thick * 0.5, 0), Vector3(cs - gap, thick, cs - gap), COLORS[HGrid.Cell.FLOOR].darkened(0.2))
				HGrid.Cell.CORE:
					_box(center + Vector3(0, -thick * 0.5, 0), Vector3(cs - gap, thick, cs - gap), COLORS[HGrid.Cell.FLOOR])
					_box(center + Vector3(0, 0.35, 0), Vector3(cs * 0.75, 0.7, cs * 0.75), COLORS[t], true)

	for c in entrance_cells:
		var p: Vector3 = grid.cell_center(c) + Vector3(0, 0.03, 0)
		_box(p, Vector3(cs - gap * 2.0, 0.06, cs - gap * 2.0), Color(0.95, 0.35, 0.25), true)

func _box(pos: Vector3, size: Vector3, color: Color, emissive: bool = false) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	var m := BoxMesh.new()
	m.size = size
	mi.mesh = m
	mi.position = pos
	mi.material_override = _mat_for(color, emissive)
	add_child(mi)
	return mi

func _mat_for(color: Color, emissive: bool) -> StandardMaterial3D:
	var key := "%s_%s" % [color.to_html(), emissive]
	if _mats.has(key):
		return _mats[key]
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	if emissive:
		mat.emission_enabled = true
		mat.emission = color
		mat.emission_energy_multiplier = 0.8
	_mats[key] = mat
	return mat
