class_name FlowField
extends RefCounted
## 从核心反向 BFS 出的距离场。敌人沿梯度下降 = 始终走最短有效路线（文档 20.2）。
## 同时用来推导入口：地图边缘上离核心最远的开口。

const INF_DIST := 1 << 28

var grid: HGrid
var dist: PackedInt32Array = PackedInt32Array()

func build(p_grid: HGrid, targets: Array) -> void:
	grid = p_grid
	dist = PackedInt32Array()
	dist.resize(grid.w * grid.h)
	dist.fill(INF_DIST)
	var queue: Array[Vector2i] = []
	for t in targets:
		if grid.is_walkable(t):
			dist[t.y * grid.w + t.x] = 0
			queue.append(t)
	var head := 0
	while head < queue.size():
		var c: Vector2i = queue[head]
		head += 1
		var d := dist[c.y * grid.w + c.x]
		for dir in HGrid.DIRS:
			var n: Vector2i = c + dir
			if not grid.in_bounds(n) or not grid.is_walkable(n):
				continue
			var idx := n.y * grid.w + n.x
			if dist[idx] > d + 1:
				dist[idx] = d + 1
				queue.append(n)

func at(c: Vector2i) -> int:
	if not grid.in_bounds(c):
		return INF_DIST
	return dist[c.y * grid.w + c.x]

func reachable(c: Vector2i) -> bool:
	return at(c) < INF_DIST

## 下一格：邻居中距离最小的一个。没有更优邻居时返回自身。
func next_cell(c: Vector2i) -> Vector2i:
	var best := at(c)
	var best_cell := c
	for dir in HGrid.DIRS:
		var n: Vector2i = c + dir
		var d := at(n)
		if d < best:
			best = d
			best_cell = n
	return best_cell

## 入口推导：边缘上可行走且可达核心的格子里，距离最大的那个所在的连通开口整段。
func find_entrance_cells() -> Array[Vector2i]:
	var border: Array[Vector2i] = []
	for y in grid.h:
		for x in grid.w:
			var c := Vector2i(x, y)
			if grid.is_border(c) and grid.is_walkable(c) and reachable(c):
				border.append(c)
	if border.is_empty():
		return []
	var far: Vector2i = border[0]
	for c in border:
		if at(c) > at(far):
			far = c
	# 沿边缘扩散出同一个开口（相邻的边缘可行走格）
	var opening: Array[Vector2i] = []
	var seen := {}
	var stack: Array[Vector2i] = [far]
	seen[far] = true
	while not stack.is_empty():
		var c: Vector2i = stack.pop_back()
		opening.append(c)
		for dir in HGrid.DIRS:
			var n: Vector2i = c + dir
			if seen.has(n):
				continue
			if grid.is_border(n) and grid.is_walkable(n) and reachable(n):
				seen[n] = true
				stack.append(n)
	return opening
