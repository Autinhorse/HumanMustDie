class_name BoardView
extends Node3D
## 地图表现。风格参考 ref/Arrow 05.jpg：地面是一整块平面（只靠细缝和颜色分格），
## 墙是立在平面上的块，侧面只出现在岛的轮廓上，岛底挂不规则岩体。
##
## 整张地图合并成一个带顶点色的 ArrayMesh（一次 draw call）。
## 岩体按格子程序化生成 —— 以后地块是随机拼的，岩体必须跟着地图变。

var grid: HGrid = null

var _board: MeshInstance3D = null
var _water: MeshInstance3D = null
var _water_mat: StandardMaterial3D = null
var _water_y := 0.0
var _core_t := 0.0

# 本次构建缓存的尺寸与配色
var _cs := 2.0
var _thick := 0.25
var _wall_h := 1.0
var _obs_h := 1.35
var _bridge_thick := 0.15
var _line_w := 0.06
var _ao_corner := 0.34
var _ao_side := 0.24
var _ao_subdiv := 4
var _ao_radius := 1.25
var _lift := 0.002
var _c_floor_side := Color.GRAY
var _c_bridge_side := Color.GRAY
var _c_wall_top := Color.WHITE
var _c_wall_side := Color.WHITE
var _c_obs_top := Color.GRAY
var _c_obs_side := Color.GRAY
var _c_line := Color.GRAY

func build(p_grid: HGrid, entrance_cells: Array) -> void:
	grid = p_grid
	for c in get_children():
		remove_child(c)
		c.queue_free()

	var art := Cfg.art
	var pal: Dictionary = art.get("palette", {})
	var board_cfg: Dictionary = art.get("board", {})
	_cs = grid.cell_size
	_wall_h = Cfg.num("grid.wall_height", 1.0)
	_thick = Cfg.num("grid.floor_thickness", 0.25)
	_obs_h = _wall_h * float(board_cfg.get("obstacle_height_mul", 1.35))
	_bridge_thick = _thick * float(board_cfg.get("bridge_thickness_mul", 0.6))
	_line_w = float(board_cfg.get("grid_line_width", 0.06))
	_lift = float(board_cfg.get("tile_lift", 0.002))
	_ao_corner = float(board_cfg.get("ao_corner", 0.34))
	_ao_side = float(board_cfg.get("ao_side", 0.24))
	_ao_subdiv = maxi(int(board_cfg.get("ao_subdiv", 4)), 1)
	_ao_radius = float(board_cfg.get("ao_radius", 1.25))

	var floor_tops: Array = pal.get("floor_top", ["#DED6C4"])
	var floor_weights: Array = pal.get("floor_top_weights", [1.0])
	var bridge_top := _col(pal, "bridge_top", Color(0.85, 0.78, 0.64))
	_c_floor_side = _col(pal, "floor_side", Color(0.62, 0.58, 0.53))
	_c_bridge_side = _col(pal, "bridge_side", _c_floor_side)
	_c_wall_top = _col(pal, "wall_top", Color(0.91, 0.89, 0.84))
	_c_wall_side = _col(pal, "wall_side", Color(0.74, 0.71, 0.64))
	_c_obs_top = _col(pal, "obstacle_top", Color(0.54, 0.50, 0.47))
	_c_obs_side = _col(pal, "obstacle_side", Color(0.43, 0.39, 0.36))
	_c_line = _col(pal, "grid_line", Color(0.70, 0.66, 0.59))
	var rock_top := _col(pal, "rock_top", Color(0.55, 0.49, 0.45))
	var rock_deep := _col(pal, "rock_deep", Color(0.42, 0.36, 0.32))
	var entrance_col := _col(pal, "entrance", Color(0.89, 0.40, 0.29))

	var rock_cfg: Dictionary = art.get("rock", {})
	var rng := RandomNumberGenerator.new()
	rng.seed = int(rock_cfg.get("seed", 20260911))

	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	# -1 = 不做平滑。盒子必须是硬边，否则相邻面的法线被平均掉，每块砖看起来都是鼓的。
	st.set_smooth_group(-1)

	var entrance_set := {}
	for c in entrance_cells:
		entrance_set[c] = true

	for y in grid.h:
		for x in grid.w:
			var cell := Vector2i(x, y)
			var t := grid.get_cell(cell)
			if t == HGrid.Cell.VOID:
				continue
			var center := grid.cell_center(cell)

			# --- 地面：整片共面，只靠细缝和颜色分格，不做成一格一个凸块
			var ground_color: Color = bridge_top if t == HGrid.Cell.BRIDGE else _pick(floor_tops, floor_weights, rng)
			if entrance_set.has(cell):
				ground_color = entrance_col
			_ground_tile(st, cell, center, ground_color)

			# --- 岛的轮廓：只有挨着空地（或出图）的那一面才有侧面
			var bottom: float = -(_bridge_thick if t == HGrid.Cell.BRIDGE else _thick)
			var side_color: Color = _c_bridge_side if t == HGrid.Cell.BRIDGE else _c_floor_side
			for d in HGrid.DIRS:
				if _is_open(cell + d):
					_side_quad(st, center, d, 0.0, bottom, side_color)

			# --- 立在地面上的东西
			if t == HGrid.Cell.WALL:
				_block(st, cell, center, _wall_h, _c_wall_top, _c_wall_side, HGrid.Cell.WALL, 1.0)
			elif t == HGrid.Cell.OBSTACLE:
				_block(st, cell, center, _obs_h, _c_obs_top, _c_obs_side, HGrid.Cell.OBSTACLE, 0.78)

			# --- 岛底岩体：只有能被看到的边缘格才需要
			if t != HGrid.Cell.BRIDGE and _touches_open(cell):
				_rock_column(st, center, bottom, rock_cfg, rng, rock_top, rock_deep)

	st.generate_normals()
	_board = MeshInstance3D.new()
	_board.name = "Board"
	_board.mesh = st.commit()
	_board.material_override = _board_material()
	add_child(_board)

	_build_core(pal)
	_build_under_clouds()

# ---------------------------------------------------------------- 构件

## 相邻格是不是"空的"（空地或出图）—— 决定要不要画侧面和岩体
func _is_open(cell: Vector2i) -> bool:
	return not grid.in_bounds(cell) or grid.get_cell(cell) == HGrid.Cell.VOID

func _touches_open(cell: Vector2i) -> bool:
	for d in HGrid.DIRS:
		if _is_open(cell + d):
			return true
	return false

## 一格地面：整格的缝色打底 + 稍微抬起、四周内缩的面色。出细缝但保持共面，不产生凸块。
func _ground_tile(st: SurfaceTool, cell: Vector2i, center: Vector3, color: Color) -> void:
	# 缝色和面色都按同样的细分画，否则缝线不会跟着变暗，会在暗部里留下一张亮网格
	if _line_w > 0.0:
		_subdiv_quad(st, center, _cs, 0.0, _c_line)
	_subdiv_quad(st, center, _cs - _line_w, _lift, color)

## 把一格切成 N×N 小块，每个顶点单独算遮蔽。
## 一格一个四边形时 AO 只能在四个角取值，暗部会被摊成两米宽的糊。
func _subdiv_quad(st: SurfaceTool, center: Vector3, size: float, y: float, color: Color) -> void:
	var n := _ao_subdiv
	var step: float = size / float(n)
	var x0: float = center.x - size * 0.5
	var z0: float = center.z - size * 0.5
	for j in n:
		for i in n:
			var ax: float = x0 + float(i) * step
			var az: float = z0 + float(j) * step
			var bx: float = ax + step
			var bz: float = az + step
			_quad(st,
				Vector3(ax, y, az), Vector3(bx, y, az),
				Vector3(bx, y, bz), Vector3(ax, y, bz), color,
				PackedFloat32Array([_ao_at(ax, az), _ao_at(bx, az), _ao_at(bx, bz), _ao_at(ax, bz)]))

## 地面上任意一点的遮蔽：取到最近遮挡物的距离衰减。
## 注意是取最大值不是累加 —— 累加的话墙中段会被好几格叠满、端头只有一格，
## 两者亮度差很大，墙的两端就会出现明显的突变。
func _ao_at(x: float, z: float) -> float:
	if _ao_corner <= 0.0:
		return 1.0
	var here := grid.world_to_cell(Vector3(x, 0.0, z))
	var occ := 0.0
	var reach := int(ceil(_ao_radius / _cs)) + 1
	var half := _cs * 0.5
	for dy in range(-reach, reach + 1):
		for dx in range(-reach, reach + 1):
			var c := here + Vector2i(dx, dy)
			if not _blocks(c):
				continue
			var cc := grid.cell_center(c)
			# 到该格矩形的距离（在格子里就是 0）
			var ex: float = max(absf(x - cc.x) - half, 0.0)
			var ez: float = max(absf(z - cc.z) - half, 0.0)
			var d: float = sqrt(ex * ex + ez * ez)
			occ = max(occ, 1.0 - d / _ao_radius)
	# 平滑一下，贴墙处最重、外沿收得干净
	occ = clampf(occ, 0.0, 1.0)
	occ = occ * occ * (3.0 - 2.0 * occ)
	return 1.0 - _ao_corner * occ

## 高出地面、会投下遮蔽的格子
func _blocks(cell: Vector2i) -> bool:
	var t := grid.get_cell(cell)
	return t == HGrid.Cell.WALL or t == HGrid.Cell.OBSTACLE

## 立方块（墙/障碍）。和同类相邻的那一面不画，连成一条完整的墙。
func _block(st: SurfaceTool, cell: Vector2i, center: Vector3, height: float,
		top_color: Color, side_color: Color, same_type: int, shrink: float) -> void:
	var size := _cs * shrink
	_top_quad(st, center, size, height, top_color)
	for d in HGrid.DIRS:
		if shrink >= 1.0 and grid.get_cell(cell + d) == same_type:
			continue
		_side_quad(st, center, d, height, 0.0, side_color, size)

func _top_quad(st: SurfaceTool, center: Vector3, size: float, y: float, color: Color,
		ao: PackedFloat32Array = PackedFloat32Array()) -> void:
	var h := size * 0.5
	_quad(st,
		center + Vector3(-h, y, -h), center + Vector3(h, y, -h),
		center + Vector3(h, y, h), center + Vector3(-h, y, h), color, ao)

## 朝 dir 方向的一面竖直面，从 y_top 落到 y_bottom
func _side_quad(st: SurfaceTool, center: Vector3, dir: Vector2i, y_top: float, y_bottom: float,
		color: Color, size: float = -1.0) -> void:
	var s: float = _cs if size < 0.0 else size
	var h := s * 0.5
	var n := Vector3(float(dir.x), 0.0, float(dir.y))
	var side := Vector3(-n.z, 0.0, n.x)
	var edge := center + n * h
	# 绕序从底边起，法线才朝外；反了的话整面会被当成背光面渲染成黑的
	# 竖直面越靠下越暗：墙根和崖壁底部自然产生遮蔽感
	var lo := 1.0 - _ao_side
	_quad(st,
		edge - side * h + Vector3(0, y_bottom, 0),
		edge + side * h + Vector3(0, y_bottom, 0),
		edge + side * h + Vector3(0, y_top, 0),
		edge - side * h + Vector3(0, y_top, 0), color,
		PackedFloat32Array([lo, lo, 1.0, 1.0]))

func _rock_column(st: SurfaceTool, center: Vector3, top_y: float, rock_cfg: Dictionary,
		rng: RandomNumberGenerator, top_color: Color, deep_color: Color) -> void:
	# 1) 实心岩层：四面齐平不收缩，岛才有厚度，不然地表就是一层薄片挂着牙齿
	var solid := float(rock_cfg.get("solid_depth", 1.6))
	var solid_bottom := top_y - solid
	for d in HGrid.DIRS:
		_side_quad(st, center, d, top_y, solid_bottom, top_color)

	# 2) 实心层下面才是长短不一、带锥度的石柱。宽度和有无都随机，避免整圈像锯齿。
	if rng.randf() < float(rock_cfg.get("skip_chance", 0.22)):
		return
	var depth: float
	if rng.randf() < float(rock_cfg.get("edge_long_chance", 0.55)):
		depth = rng.randf_range(float(rock_cfg.get("edge_depth_min", 1.5)),
			float(rock_cfg.get("edge_depth_max", 5.5)))
	else:
		depth = rng.randf_range(float(rock_cfg.get("inner_depth_min", 0.6)),
			float(rock_cfg.get("inner_depth_max", 1.8)))
	var taper := float(rock_cfg.get("taper", 0.45))
	var variance := float(rock_cfg.get("taper_variance", 0.5))
	var jitter := float(rock_cfg.get("jitter", 0.55))
	var scale: float = clampf(taper * rng.randf_range(1.0 - variance, 1.0 + variance), 0.15, 0.95)
	var off := Vector3(rng.randf_range(-jitter, jitter), 0.0, rng.randf_range(-jitter, jitter))

	var top_scale := rng.randf_range(float(rock_cfg.get("top_scale_min", 0.62)), 1.0)
	var h := _cs * 0.5 * top_scale
	var top_off := Vector3(rng.randf_range(-1.0, 1.0), 0.0, rng.randf_range(-1.0, 1.0)) * (_cs * 0.5 - h)
	var bh := _cs * 0.5 * scale * top_scale
	var y1 := solid_bottom - depth
	var t0 := center + top_off + Vector3(-h, solid_bottom, -h)
	var t1 := center + top_off + Vector3(h, solid_bottom, -h)
	var t2 := center + top_off + Vector3(h, solid_bottom, h)
	var t3 := center + top_off + Vector3(-h, solid_bottom, h)
	var b0 := center + top_off + off + Vector3(-bh, y1, -bh)
	var b1 := center + top_off + off + Vector3(bh, y1, -bh)
	var b2 := center + top_off + off + Vector3(bh, y1, bh)
	var b3 := center + top_off + off + Vector3(-bh, y1, bh)
	_quad(st, b3, b2, b1, b0, deep_color)
	_quad(st, b0, b1, t1, t0, deep_color)
	_quad(st, b1, b2, t2, t1, deep_color)
	_quad(st, b2, b3, t3, t2, deep_color)
	_quad(st, b3, b0, t0, t3, deep_color)

## ao 传 4 个值（对应 a/b/c/d 四个角）时按顶点压暗，用来烘焙环境光遮蔽
func _quad(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, color: Color,
		ao: PackedFloat32Array = PackedFloat32Array()) -> void:
	var pts := [a, b, c, d]
	var has_ao := ao.size() == 4
	for k in [0, 1, 2, 0, 2, 3]:
		var f: float = ao[k] if has_ao else 1.0
		st.set_color(Color(color.r * f, color.g * f, color.b * f, color.a))
		st.add_vertex(pts[k])

## 岛下方铺一层云。用 FogVolume 做真正的体积云 —— 之前用压扁的球体 +
## 无光照材质，结果是一个个纯色圆片，没有渐变也没有体积感。
func _build_under_clouds() -> void:
	var cfg: Dictionary = Cfg.art.get("under_clouds", {})
	if not bool(cfg.get("enabled", true)):
		return
	var rng := RandomNumberGenerator.new()
	rng.seed = int(Cfg.art.get("rock", {}).get("seed", 20260911)) + 91

	var root := Node3D.new()
	root.name = "UnderClouds"
	add_child(root)

	var margin := float(cfg.get("margin", 2.0)) * _cs
	var w: float = float(grid.w) * _cs
	var h: float = float(grid.h) * _cs
	var yc := float(cfg.get("y_center", -9.5))
	var ys := float(cfg.get("y_spread", 2.6))
	var albedo := _col(cfg, "color", Color(0.92, 0.95, 0.96))
	for i in int(cfg.get("count", 22)):
		var fv := FogVolume.new()
		fv.shape = RenderingServer.FOG_VOLUME_SHAPE_ELLIPSOID
		var r := rng.randf_range(float(cfg.get("radius_min", 5.0)), float(cfg.get("radius_max", 11.0)))
		fv.size = Vector3(r * 2.0, r * 2.0 * float(cfg.get("flatten", 0.5)), r * 2.0 * rng.randf_range(0.75, 1.25))
		var fm := FogMaterial.new()
		fm.density = float(cfg.get("density", 4.0)) * rng.randf_range(0.7, 1.3)
		fm.albedo = albedo
		fm.edge_fade = float(cfg.get("edge_fade", 0.35))
		# 光只从一个方向来，背光那半会发灰。加一点自发光把云整体提白。
		fm.emission = _col(cfg, "emission", Color(0.30, 0.33, 0.35))
		fv.material = fm
		fv.position = Vector3(
			rng.randf_range(-margin, w + margin),
			yc + rng.randf_range(-ys, ys),
			rng.randf_range(-margin, h + margin))
		root.add_child(fv)

func _build_core(pal: Dictionary) -> void:
	var cores := grid.cells_of_type(HGrid.Cell.CORE)
	if cores.is_empty():
		return
	var sum := Vector3.ZERO
	for c in cores:
		sum += grid.cell_center(c)
	var center: Vector3 = sum / float(cores.size())

	var rim := MeshInstance3D.new()
	rim.name = "CoreRim"
	var torus := TorusMesh.new()
	torus.inner_radius = _cs * 0.72
	torus.outer_radius = _cs * 0.98
	torus.rings = 28
	torus.ring_segments = 8
	rim.mesh = torus
	rim.position = center + Vector3(0, 0.12, 0)
	var rim_mat := StandardMaterial3D.new()
	rim_mat.albedo_color = _col(pal, "core_rim", Color(0.93, 0.91, 0.86))
	rim_mat.roughness = 0.95
	rim_mat.metallic_specular = 0.12
	rim.material_override = rim_mat
	add_child(rim)

	_water = MeshInstance3D.new()
	_water.name = "CoreWater"
	var disc := CylinderMesh.new()
	disc.top_radius = _cs * 0.76
	disc.bottom_radius = _cs * 0.76
	disc.height = 0.14
	disc.radial_segments = 28
	_water.mesh = disc
	_water.position = center + Vector3(0, 0.09, 0)
	var water_mat := StandardMaterial3D.new()
	var water_col := _col(pal, "core_water", Color(0.25, 0.70, 0.69))
	water_mat.albedo_color = water_col
	water_mat.roughness = 0.2
	water_mat.emission_enabled = true
	water_mat.emission = water_col
	water_mat.emission_energy_multiplier = 0.45
	_water.material_override = water_mat
	_water_mat = water_mat
	_water_y = _water.position.y
	add_child(_water)

# ---------------------------------------------------------------- 杂项

func _board_material() -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	# SurfaceTool 里存的是 sRGB 值，不声明的话会被当成线性色用，整张图会发白
	mat.vertex_color_is_srgb = true
	mat.roughness = 0.95
	mat.metallic = 0.0
	mat.metallic_specular = 0.08
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


## 核心是全局焦点，让它缓慢呼吸：发光强度起伏 + 水面上下浮动
func _process(delta: float) -> void:
	if _water == null or _water_mat == null:
		return
	var cfg: Dictionary = Cfg.art.get("core_fx", {})
	_core_t += delta
	var pulse: float = sin(_core_t * float(cfg.get("pulse_speed", 1.1)))
	_water_mat.emission_energy_multiplier = 0.45 + float(cfg.get("pulse_amount", 0.45)) * (pulse * 0.5 + 0.5)
	_water.position.y = _water_y + sin(_core_t * float(cfg.get("bob_speed", 0.9))) * float(cfg.get("bob_amount", 0.022))
