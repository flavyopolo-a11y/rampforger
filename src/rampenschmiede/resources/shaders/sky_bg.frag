#version 330
uniform mat4 u_inv_vp;
in vec2 v_ndc;
out vec4 f_color;
//SKY
void main() {
    vec4 near = u_inv_vp * vec4(v_ndc, -1.0, 1.0);
    vec4 far = u_inv_vp * vec4(v_ndc, 1.0, 1.0);
    vec3 d = normalize(far.xyz / far.w - near.xyz / near.w);
    f_color = vec4(sky_color(d), 1.0);
}
