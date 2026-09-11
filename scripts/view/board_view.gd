class_name BoardView
extends Node3D
## 地图表现。风格参考 ref/Arrow 05.jpg：奶白顶面 + 灰岩侧面 + 岛底不规则岩体。
##
## 整张地图合并成一个带顶点色的 ArrayMesh（一次 draw call），岩体按格子程序化生成 ——
## 以后地块是随机拼的，岩体必须跟着地图变，所以不能预烘焙成固定模型。

var grid: HGrid = null

var _board: MeshInstance3D = null
var _water: MeshInstance3D = null
var _clouds: Node3D = null

func build(p_grid: HGrid, entrance_cells: Array) -> void:
	grid = p_grid
	for c in get_children():
		remove_child(c)
		c.queue_free()

	var art := Cfg.art
	var pal: Dictionary = art.get("palette", {})
	var board_cfg: Dictionary = art.get("board", {})
	var cs := grid.cell_size
	var wall_h := Cfg.num("grid.wall_height", 1.0)
	var thick := Cfg.num("grid.floor_thickness", 0.25)
	var gap := float(board_cfg.get("cell_gap", 0.06))
	var wall_gap := float(board_cfg.get("wall_cell_gap", 0.03))
	var cap := float(board_cfg.get("cap_thickness", 0.06))
	var bridge_inset := float(board_cfg.get("bridge_inset", 0.06))

	var floor_tops: Array = pal.get("floor_top", ["#EDE8DB"])
	var floor_weights: Array = pal.get("floor_top_weights", [1.0])
	var floor_side := _col(pal, "floor_side", Color(0.65, 0.62, 0.57))
	var bridge_top := _col(pal, "bridge_top", Color(0.85, 0.78, 0.64))
	var bridge_side := _col(pal, "bridge_side", floor_side)
	var wall_top := _col(pal, "wall_top", Color(0.96, 0.95, 0.92))
	var wall_side := _col(pal, "wall_side", Color(0.83, 0.80, 0.75))
	var obs_top := _col(pal, "obstacle_top", Color(0.54, 0.50, 0.47))
	var obs_side := _col(pal, "obstacle_side", Color(0.43, 0.39, 0.36))
	var rock_top := _col(pal, "rock_top", Color(0.55, 0.49, 0.45))
	var rock_deep := _col(pal, "rock_deep", Color(0.42, 0.36, 0.32))
	var entrance_col := _col(pal, "entrance", Color(0.89, 0.40, 0.29))

	var rock_cfg: Dictionary = art.get("rock", {})
	var rng := RandomNumberGenerator.new()
	rng.seed = int(rock_cfg.get("seed", 20260911))

	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)

	for y in grid.h:
		for x in grid.w:
			var cell := Vector2i(x, y)
			var t := grid.get_cell(cell)
			var c := grid.cell_center(cell)
			match t:
				HGrid.Cell.VOID:
					continue
				HGrid.Cell.BRIDGE:
					# 桥：薄板、稍微内缩，下面不长岩体（它本来就是没支撑的）
					_slab(st, c, cs - gap - bridge_inset, thick * 0.8, cap, bridge_top, bridge_side)
					continue
				HGrid.Cell.WALL:
					_slab(st, c, cs - gap, thick, cap, _pick(floor_tops, floor_weights, rng), floor_side)
					_slab(st, c + Vector3(0, wall_h, 0), cs - wall_gap, wall_h, cap * 1.6, wall_top, wall_side)
				HGrid.Cell.OBSTACLE:
					_slab(st, c, cs - gap, thick, cap, _pick(floor_tops, floor_weights, rng), floor_side)
					_slab(st, c + Vector3(0, wall_h * 1.35, 0), cs * 0.78, wall_h * 1.35, cap, obs_top, obs_side)
				_:
					_slab(st, c, cs - gap, thick, cap, _pick(floor_tops, floor_weights, rng), floor_side)

			# 岛底岩体：边缘格长出长岩柱，内部格短一截
			_rock_column(st, cell, c, cs, thick, rock_cfg, rng, rock_top, rock_deep)

	for cell in entrance_cells:
		var p: Vector3 = grid.cell_center(cell) + Vector3(0, 0.035, 0)
		_box(st, p, Vector3(cs - gap * 2.5, 0.05, cs - gap * 2.5), entrance_col, entrance_col, 1.0, Vector2.ZERO)

	st.generate_normals()
	_board = MeshInstance3D.new()
	_board.name = "Board"
	_board.mesh = st.commit()
	_board.material_override = _board_material()
	add_child(_board)

	_build_core(pal)
	_build_clouds(art, cs)

# ---------------------------------------------------------------- 构件

## 一块地砖 = 顶盖（顶面色，很薄）+ 下方主体（侧面色），参考图里就是这种两段式
func _slab(st: SurfaceTool, top_center: Vector3, size: float, height: float,
		cap: float, top_color: Color, side_color: Color) -> void:
	var body_h: float = max(height - cap, 0.01)
	_box(st, top_center + Vector3(0, -cap - body_h * 0.5, 0),
		Vector3(size, body_h, size), side_color, side_color, 1.0, Vector2.ZERO)
	_box(st, top_center + Vector3(0, -cap * 0.5, 0),
		Vector3(size, cap, size), top_color, top_color, 1.0, Vector2.ZERO)

func _rock_column(st: SurfaceTool, cell: Vector2i, center: Vector3, cs: float, thick: float,
		rock_cfg: Dictionary, rng: RandomNumberGenerator, top_color: Color, deep_color: Color) -> void:
	var on_edge := false
	for d in HGrid.DIRS:
		var n := grid.get_cell(cell + d)
		if n == HGrid.Cell.VOID or n == HGrid.Cell.BRIDGE:
			on_edge = true
			break
	if grid.is_border(cell):
		on_edge = true

	var depth: float
	if on_edge and rng.randf() < float(rock_cfg.get("edge_long_chance", 0.55)):
		depth = rng.randf_range(float(rock_cfg.get("edge_depth_min", 2.2)),
			float(rock_cfg.get("edge_depth_max", 7.0)))
	else:
		depth = rng.randf_range(float(rock_cfg.get("inner_depth_min", 1.2)),
			float(rock_cfg.get("inner_depth_max", 2.6)))

	var taper := float(rock_cfg.get("taper", 0.45))
	var variance := float(rock_cfg.get("taper_variance", 0.5))
	var jitter := float(rock_cfg.get("jitter", 0.55))
	var scale: float = clampf(taper * rng.randf_range(1.0 - variance, 1.0 + variance), 0.15, 0.95)
	var off := Vector2(rng.randf_range(-jitter, jitter), rng.randf_range(-jitter, jitter))
	_box(st, center + Vector3(0, -thick - depth * 0.5, 0), Vector3(cs, depth, cs),
		top_color, deep_color, scale, off)

## 轴对齐盒子，底面可以收缩+偏移（做锥形岩柱）。顶面用 top_color，其余用 side_color。
func _box(st: SurfaceTool, center: Vector3, size: Vector3, top_color: Color, side_color: Color,
		bottom_scale: float, bottom_offset: Vector2) -> void:
	var hx := size.x * 0.5
	var hz := size.z * 0.5
	var hy := size.y * 0.5
	var bx := hx * bottom_scale
	var bz := hz * bottom_scale
	var bo := Vector3(bottom_offset.x, 0.0, bottom_offset.y)

	var t0 := center + Vector3(-hx, hy, -hz)
	var t1 := center + Vector3(hx, hy, -hz)
	var t2 := center + Vector3(hx, hy, hz)
	var t3 := center + Vector3(-hx, hy, hz)
	var b0 := center + bo + Vector3(-bx, -hy, -bz)
	var b1 := center + bo + Vector3(bx, -hy, -bz)
	var b2 := center + bo + Vector3(bx, -hy, bz)
	var b3 := center + bo + Vector3(-bx, -hy, bz)

	_quad(st, t0, t1, t2, t3, top_color)       # 顶
	_quad(st, b3, b2, b1, b0, side_color)      # 底
	_quad(st, b0, b1, t1, t0, side_color)      # -Z
	_quad(st, b1, b2, t2, t1, side_color)      # +X
	_quad(st, b2, b3, t3, t2, side_color)      # +Z
	_quad(st, b3, b0, t0, t3, side_color)      # -X

func _quad(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, color: Color) -> void:
	for v in [a, b, c, a, c, d]:
		st.set_color(color)
		st.add_vertex(v)

func _build_core(pal: Dictionary) -> void:
	var cores := grid.cells_of_type(HGrid.Cell.CORE)
	if cores.is_empty():
		return
	var sum := Vector3.ZERO
	for c in cores:
		sum += grid.cell_center(c)
	var center: Vector3 = sum / float(cores.size())
	var cs := grid.cell_size

	var rim := MeshInstance3D.new()
	rim.name = "CoreRim"
	var torus := TorusMesh.new()
	torus.inner_radius = cs * 0.72
	torus.outer_radius = cs * 0.98
	torus.rings = 24
	torus.ring_segments = 8
	rim.mesh = torus
	rim.position = center + Vector3(0, 0.18, 0)
	var rim_mat := StandardMaterial3D.new()
	rim_mat.albedo_color = _col(pal, "core_rim", Color(0.93, 0.91, 0.86))
	rim_mat.roughness = 0.95
	rim_mat.metallic_specular = 0.15
	rim.material_override = rim_mat
	add_child(rim)

	_water = MeshInstance3D.new()
	_water.name = "CoreWater"
	var disc := CylinderMesh.new()
	disc.top_radius = cs * 0.74
	disc.bottom_radius = cs * 0.74
	disc.height = 0.22
	disc.radial_segments = 28
	_water.mesh = disc
	_water.position = center + Vector3(0, 0.14, 0)
	var water_mat := StandardMaterial3D.new()
	var water_col := _col(pal, "core_water", Color(0.25, 0.70, 0.69))
	water_mat.albedo_color = water_col
	water_mat.roughness = 0.18
	water_mat.emission_enabled = true
	water_mat.emission = water_col
	water_mat.emission_energy_multiplier = 0.5
	_water.material_override = water_mat
	add_child(_water)

func _build_clouds(art: Dictionary, cs: float) -> void:
	var cfg: Dictionary = art.get("clouds", {})
	if not bool(cfg.get("enabled", true)):
		return
	_clouds = Node3D.new()
	_clouds.name = "Clouds"
	add_child(_clouds)

	var rng := RandomNumberGenerator.new()
	rng.seed = int(art.get("rock", {}).get("seed", 20260911)) + 7
	var mat := StandardMaterial3D.new()
	mat.albedo_color = _col(art.get("palette", {}), "cloud", Color(0.92, 0.95, 0.94))
	mat.roughness = 1.0
	mat.metallic_specular = 0.0
	# 平涂：云只是背景衬托，不该接岛的投影
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	var center := grid.center_world()
	var island_radius: float = max(center.x, center.z)
	var ring_min := float(cfg.get("ring_min", 1.35)) * island_radius
	var ring_max := float(cfg.get("ring_max", 2.6)) * island_radius
	for i in int(cfg.get("count", 22)):
		var mi := MeshInstance3D.new()
		var sphere := SphereMesh.new()
		sphere.radius = rng.randf_range(float(cfg.get("radius_min", 6.0)), float(cfg.get("radius_max", 14.0)))
		sphere.height = sphere.radius * 2.0
		sphere.radial_segments = 12
		sphere.rings = 6
		mi.mesh = sphere
		mi.material_override = mat
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		var ang := rng.randf() * TAU
		var dist := rng.randf_range(ring_min, ring_max)
		mi.position = Vector3(
			center.x + cos(ang) * dist,
			rng.randf_range(float(cfg.get("y_min", -40.0)), float(cfg.get("y_max", -14.0))),
			center.z + sin(ang) * dist)
		mi.scale = Vector3(rng.randf_range(0.8, 1.3), float(cfg.get("flatten", 0.18)), rng.randf_range(0.8, 1.3))
		_clouds.add_child(mi)

# ---------------------------------------------------------------- 杂项

func _board_material() -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	# SurfaceTool 里存的是 sRGB 值，不声明的话会被当成线性色用，整张图会发白
	mat.vertex_color_is_srgb = true
	mat.roughness = 0.95
	mat.metallic = 0.0
	mat.metallic_specular = 0.12
	return mat

func _pick(colors: Array, weights: Array, rng: RandomNumberGenerator) -> Color:
	if colors.is_empty():
		return Color.WHITE
	var total := 0.0
	for i in colors.size():
		total += float(weights[i]) if i < weights.size() else 1.0
	var r := rng.randf() * total
	for i in colors.size():
		r -= float(weights[i]) if i < weights.size() else 1.0
		if r <= 0.0:
			return Color(String(colors[i]))
	return Color(String(colors[0]))

func _col(pal: Dictionary, key: String, def: Color) -> Color:
	if pal.has(key) and typeof(pal[key]) == TYPE_STRING:
		return Color(String(pal[key]))
	return def
