class_name TrapPayload
extends RefCounted
## 机关五段组件之一：伤害。damage = 单次触发；dps = 持续触发按 dt 结算。

static func apply(params: Dictionary, enemy, dt: float, source: String) -> float:
	if params.is_empty():
		return 0.0
	var amount := 0.0
	if params.has("damage"):
		amount += float(params["damage"])
	if params.has("dps"):
		amount += float(params["dps"]) * dt
	if amount <= 0.0:
		return 0.0
	return enemy.take_damage(amount, source)
