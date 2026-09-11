class_name TrapTrigger
extends RefCounted
## 机关五段组件之一：触发条件。返回 true 表示本 tick 应该发动。
## state 由机关自己持有，方便以后加"击杀重置""储能"等改件。

static func evaluate(params: Dictionary, state: Dictionary, enemies: Array, dt: float) -> bool:
	var t := String(params.get("type", "periodic"))
	var cooldown := float(params.get("cooldown", 0.0))
	var ready: bool = float(state.get("cooldown_left", 0.0)) <= 0.0

	match t:
		"continuous":
			return enemies.size() > 0

		"periodic":
			var need_enemy := bool(params.get("require_enemy", true))
			if ready and (enemies.size() > 0 or not need_enemy):
				state["cooldown_left"] = cooldown
				return true
			return false

		"on_enter":
			var prev: Dictionary = state.get("prev_ids", {})
			var now := {}
			var entered := false
			for e in enemies:
				now[e.uid] = true
				if not prev.has(e.uid):
					entered = true
			state["prev_ids"] = now
			if entered and ready:
				state["cooldown_left"] = cooldown
				return true
			return false

		"threshold_count":
			var min_count := int(params.get("min_count", 1))
			var max_wait := float(params.get("max_wait", 2.0))
			if enemies.is_empty():
				state["presence"] = 0.0
				return false
			state["presence"] = float(state.get("presence", 0.0)) + dt
			if not ready:
				return false
			if enemies.size() >= min_count or float(state["presence"]) >= max_wait:
				state["cooldown_left"] = cooldown
				state["presence"] = 0.0
				return true
			return false

	push_warning("未知 trigger 类型: %s" % t)
	return false
