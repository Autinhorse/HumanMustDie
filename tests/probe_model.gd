extends Node
func _ready() -> void:
	var packed = load("res://assets/models/swordman.glb")
	var root: Node3D = packed.instantiate()
	add_child(root)
	_dump(root, 0)
	get_tree().quit(0)

func _dump(n: Node, depth: int) -> void:
	var pad := "  ".repeat(depth)
	if n is Node3D:
		var t: Transform3D = n.transform
		var e: Vector3 = t.basis.get_euler() * 180.0 / PI
		print("%s%s [%s] pos=(%.3f,%.3f,%.3f) euler=(%.1f,%.1f,%.1f) X=%s Y=%s Z=%s" % [
			pad, n.name, n.get_class(), t.origin.x, t.origin.y, t.origin.z, e.x, e.y, e.z,
			_v(t.basis.x), _v(t.basis.y), _v(t.basis.z)])
	else:
		print("%s%s [%s]" % [pad, n.name, n.get_class()])
	for c in n.get_children():
		_dump(c, depth + 1)

func _v(v: Vector3) -> String:
	return "(%.2f,%.2f,%.2f)" % [v.x, v.y, v.z]
