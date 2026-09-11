class_name TrapStatus
extends RefCounted
## 机关五段组件之一：状态。原型只做减速，火/冰/电/毒留到第二阶段。

static func apply(params: Dictionary, enemy, source: String) -> void:
	if params.is_empty():
		return
	if params.has("slow"):
		enemy.apply_slow(float(params["slow"]), float(params.get("duration", 1.0)), source)
