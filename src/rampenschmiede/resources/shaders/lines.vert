#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in vec3 in_color;
out vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_color = in_color;
}
