#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in vec3 in_normal;
in vec3 in_color;
in float in_selected;
out vec3 v_normal;
out vec3 v_color;
out float v_selected;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_normal = in_normal;
    v_color = in_color;
    v_selected = in_selected;
}
