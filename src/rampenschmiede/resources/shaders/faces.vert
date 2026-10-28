#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in vec3 in_normal;
in vec3 in_color;
in vec2 in_uv;
in float in_layer;
in float in_layer2;
in float in_blend;
in float in_selected;
in vec3 in_lightmap;
out vec3 v_pos;
out vec3 v_normal;
out vec3 v_color;
out vec2 v_uv;
flat out float v_layer;
flat out float v_layer2;
out float v_blend;
out float v_selected;
out vec3 v_lightmap;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_pos = in_pos;
    v_normal = in_normal;
    v_color = in_color;
    v_uv = in_uv;
    v_layer = in_layer;
    v_layer2 = in_layer2;
    v_blend = in_blend;
    v_selected = in_selected;
    v_lightmap = in_lightmap;
}
