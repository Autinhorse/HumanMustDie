class_name TrapDisplacement
extends RefCounted
## 机关五段组件之一：冲击/位移。冲击先进敌人的积累槽，超过稳定值才真正位移（文档 8）。

static func apply(params: Dictionary, enemy, facing: Vector2i, source: String) -> void:
	if params.is_empty():
		return
	var force := float(params.get("force", 0.0))
	if force <= 0.0:
		return
	var up := float(params.get("up", 0.0))
	var dir := Vector3(float(facing.x), 0.0, float(facing.y))
	enemy.apply_impulse(dir, force, up, source)
