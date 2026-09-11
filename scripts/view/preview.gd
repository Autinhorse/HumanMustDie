class_name PlacementPreview
extends Node3D
## 放置预览：覆盖范围 + 朝向箭头（文档 14.2：战斗前必须能看到机关覆盖范围与方向）
## 也用于展示已放置机关被选中时的覆盖范围。

var grid: HGrid = null
var _pool: Array[MeshInstance3D] = []
var _arrow: MeshInstance3D = null
var _mat_ok: StandardMaterial3D = null
var _mat_bad: StandardMaterial3D = null
var _mat_sel: StandardMaterial3D = null

func setup(p_grid: HGrid) -> void:
	grid = p_grid
	for c in get_children():
		remove_child(c)
		c.queue_free()
	_pool.clear()
	_mat_ok = _make_mat(Color(0.35, 0.95, 0.55, 0.35))
	_mat_bad = _make_mat(Color(0.95, 0.25, 0.25, 0.35))
	_mat_sel = _make_mat(Color(0.95, 0.85, 0.30, 0.30))
	_arrow = MeshInstance3D.new()
	var prism := PrismMesh.new()
	prism.size = Vector3(grid.cell_size * 0.4, grid.cell_size * 0.5, 0.15)
	_arrow.mesh = prism
	_arrow.material_override = _make_mat(Color(1, 1, 1, 0.85))
	_arrow.visible = false
	add_child(_arrow)

func _make_mat(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m

func clear() -> void:
	for q in _pool:
		q.visible = false
	if _arrow != null:
		_arrow.visible = false

## mode: "ok" / "bad" / "select"
func show_cells(cells: Array, origin: Vector2i, facing: Vector2i, mode: String, show_arrow: bool, lift: float = 0.05) -> void:
	clear()
	if grid == null:
		return
	var mat: StandardMaterial3D = _mat_ok
	if mode == "bad":
		mat = _mat_bad
	elif mode == "select":
		mat = _mat_sel
	var i := 0
	for c in cells:
		var q := _quad(i)
		q.material_override = mat
		q.position = grid.cell_center(c) + Vector3(0, lift, 0)
		q.visible = true
		i += 1
	# 原点格子高亮一层
	var o := _quad(i)
	o.material_override = mat
	o.position = grid.cell_center(origin) + Vector3(0, lift + 0.02, 0)
	o.scale = Vector3(0.6, 1.0, 0.6)
	o.visible = true

	if show_arrow and (facing.x != 0 or facing.y != 0):
		_arrow.visible = true
		_arrow.rotation = Vector3(-PI * 0.5, atan2(float(facing.x), float(facing.y)), 0)
		_arrow.position = grid.cell_center(origin) + Vector3(float(facing.x), 0.0, float(facing.y)) * (grid.cell_size * 0.5) + Vector3(0, lift + 0.4, 0)

func _quad(i: int) -> MeshInstance3D:
	while _pool.size() <= i:
		var mi := MeshInstance3D.new()
		var q := QuadMesh.new()
		q.size = Vector2(grid.cell_size * 0.92, grid.cell_size * 0.92)
		mi.mesh = q
		mi.rotation = Vector3(-PI * 0.5, 0, 0)
		mi.visible = false
		add_child(mi)
		_pool.append(mi)
	var node := _pool[i]
	node.scale = Vector3.ONE
	return node
