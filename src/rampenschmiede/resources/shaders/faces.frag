#version 330
uniform vec3 u_light_dir;
uniform float u_flat;
uniform float u_textured;
uniform sampler2DArray u_textures;
in vec3 v_normal;
in vec3 v_color;
in vec2 v_uv;
flat in float v_layer;
in float v_selected;
out vec4 f_color;
void main() {
    vec3 n = normalize(v_normal);
    // Zwei feste Lichter, damit jede Seite eines Würfels unterscheidbar bleibt.
    float key = max(dot(n, u_light_dir), 0.0);
    float fill = max(dot(n, normalize(vec3(-0.6, -0.3, 0.2))), 0.0);
    float light = mix(0.38 + 0.5 * key + 0.18 * fill, 1.0, u_flat);
    vec3 base = v_color;
    if (u_textured > 0.5 && v_layer > 0.5) {
        base = texture(u_textures, vec3(v_uv, v_layer)).rgb;
        light = mix(0.55 + 0.4 * key + 0.12 * fill, 1.0, u_flat);
    }
    vec3 color = base * light;
    color = mix(color, vec3(1.0, 0.25, 0.2), v_selected * 0.45);
    f_color = vec4(color, 1.0);
}
