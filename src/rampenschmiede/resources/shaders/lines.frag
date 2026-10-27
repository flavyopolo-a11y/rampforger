#version 330
uniform vec4 u_override;
in vec3 v_color;
out vec4 f_color;
void main() {
    // u_override.a > 0: alle Linien in einer Farbe (z. B. dunkle Kanten in 3D)
    f_color = u_override.a > 0.0 ? vec4(u_override.rgb, 1.0) : vec4(v_color, 1.0);
}
