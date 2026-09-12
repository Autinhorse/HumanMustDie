// 屏幕空间描边：比较相邻像素的深度和法线，差异大的地方画线。
// 挂在相机上的全屏四边形，render_priority 拉高保证在所有东西之后画。
// 需要 Forward+（法线粗糙度贴图只有 Forward+ 有）。
shader_type spatial;
// blend_mix + 只输出线本身：不能去读屏幕拷贝再整屏覆盖，那样会把半透明物体
// （地面标记、放置预览、云）全擦掉 —— Godot 的屏幕拷贝发生在半透明通道之前。
// blend_mul：把底下的颜色"压暗"而不是盖一层黑。纯黑描边在小物体上会把主体吃掉，
// 乘算能保留色相，远看是深色边缘而不是黑糊。
render_mode unshaded, fog_disabled, depth_draw_never, depth_test_disabled, cull_disabled, blend_mul;

uniform sampler2D depth_tex : hint_depth_texture, filter_nearest, repeat_disable;
uniform sampler2D normal_tex : hint_normal_roughness_texture, filter_nearest, repeat_disable;

uniform vec4 outline_color : source_color = vec4(0.30, 0.33, 0.38, 1.0);  // 乘算系数，越小越黑
uniform float thickness = 1.0;          // 线宽，单位是像素
// 正交相机下相机离场景很远，用"相对深度差"阈值会永远够不到，必须用绝对值（世界单位）
uniform float depth_threshold = 0.12;   // 相邻像素深度差超过这么多米算一条边
uniform float normal_threshold = 0.30;  // 法线夹角多大算一条边
uniform float strength = 0.8;           // 描边的不透明度
uniform float depth_fade = 120.0;       // 远处淡出，免得远景糊成一团线

void vertex() {
	POSITION = vec4(VERTEX.xy * 2.0, 1.0, 1.0);
}

float view_depth(vec2 uv, mat4 inv_proj) {
	float d = texture(depth_tex, uv).x;
	vec4 view = inv_proj * vec4(uv * 2.0 - 1.0, d, 1.0);
	return -(view.z / view.w);
}

void fragment() {
	vec2 texel = thickness / VIEWPORT_SIZE;
	float d0 = view_depth(SCREEN_UV, INV_PROJECTION_MATRIX);

	vec2 off[4] = {vec2(texel.x, 0.0), vec2(-texel.x, 0.0), vec2(0.0, texel.y), vec2(0.0, -texel.y)};
	vec3 n0 = texture(normal_tex, SCREEN_UV).xyz * 2.0 - 1.0;

	float depth_edge = 0.0;
	float normal_edge = 0.0;
	for (int i = 0; i < 4; i++) {
		vec2 uv = SCREEN_UV + off[i];
		float d = view_depth(uv, INV_PROJECTION_MATRIX);
		depth_edge = max(depth_edge, abs(d - d0));
		vec3 n = texture(normal_tex, uv).xyz * 2.0 - 1.0;
		normal_edge = max(normal_edge, 1.0 - dot(n0, n));
	}

	float e = max(smoothstep(depth_threshold, depth_threshold * 2.2, depth_edge),
	              smoothstep(normal_threshold, normal_threshold * 1.7, normal_edge));
	e *= strength * (1.0 - smoothstep(depth_fade * 0.6, depth_fade, d0));
	// 天空/背景（深度极远）不描边。Godot 的 fragment 里不能 return，用系数屏蔽。
	e *= 1.0 - step(depth_fade * 2.0, d0);

	ALBEDO = mix(vec3(1.0), outline_color.rgb, clamp(e, 0.0, 1.0));
	ALPHA = 1.0;
}
