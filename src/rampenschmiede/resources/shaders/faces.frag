#version 330
#define MAX_LIGHTS 32
uniform vec3 u_light_dir;
uniform float u_flat;
uniform float u_textured;
uniform sampler2DArray u_textures;
// Licht-Vorschau
uniform float u_lit;
uniform float u_fullbright;
uniform int u_light_count;
uniform vec4 u_lpos[MAX_LIGHTS];    // Position, Reichweite
uniform vec4 u_lcolor[MAX_LIGHTS];  // Farbe mal Helligkeit, 1 = Spot
uniform vec4 u_lattn[MAX_LIGHTS];   // c, l, q, 50-%-Abstand
uniform vec4 u_ldir[MAX_LIGHTS];    // Spot-Richtung, 0-%-Abstand
uniform vec4 u_lcone[MAX_LIGHTS];   // cos innen, cos außen, Exponent
uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform vec3 u_ambient;
// Himmel
uniform float u_has_sky;
uniform vec3 u_eye;
in vec3 v_pos;
in vec3 v_normal;
in vec3 v_color;
in vec2 v_uv;
flat in float v_layer;
in float v_selected;
out vec4 f_color;
//SKY

float falloff(int i, float d) {
    vec4 at = u_lattn[i];
    if (at.w > 0.0) {
        float k = 1.0 / (1.0 + (d / at.w) * (d / at.w));
        float zero = u_ldir[i].w;
        if (zero > at.w) {
            k *= 1.0 - smoothstep(at.w, zero, d);
        }
        return k;
    }
    return 1.0 / max(at.x + at.y * d + at.z * d * d, 1e-6);
}

vec3 preview_light(vec3 n) {
    if (u_fullbright > 0.5) {
        return vec3(1.0);
    }
    vec3 sum = u_ambient + u_sun_color * max(dot(n, -u_sun_dir), 0.0);
    for (int i = 0; i < u_light_count; ++i) {
        vec3 delta = u_lpos[i].xyz - v_pos;
        float d = length(delta);
        if (d > u_lpos[i].w) continue;
        vec3 l = delta / max(d, 1e-4);
        float lambert = max(dot(n, l), 0.0);
        if (lambert <= 0.0) continue;
        float k = falloff(i, d);
        if (u_lcolor[i].w > 0.5) {
            float c = dot(-l, u_ldir[i].xyz);
            vec4 cone = u_lcone[i];
            if (c <= cone.y) continue;
            if (c < cone.x) k *= (c - cone.y) / max(cone.x - cone.y, 1e-4);
            if (cone.z != 1.0) k *= pow(c, cone.z);
        }
        sum += u_lcolor[i].rgb * (lambert * k);
    }
    // Lightmaps dürfen in Source über 1 gehen (Überbelichtung), mehr als doppelt bringt nichts
    return min(sum, vec3(2.0));
}

void main() {
    // Skybox-Flächen tragen ihre Textur-Ebene negativ (-Ebene - 1), Entity-Kästchen -0,25
    // (sie bleiben in der Licht-Vorschau sichtbar statt dunkel)
    bool sky_face = v_layer < -0.5;
    bool marker = v_layer < -0.1 && !sky_face;
    float layer = sky_face ? -v_layer - 1.0 : (marker ? 0.0 : v_layer);
    // Durchsichtige Materialien (Blätter, Gitter): Aufschlag 512 = $alphatest, 1024 = $translucent
    float cutout = 0.0;
    if (layer > 1023.5) { layer -= 1024.0; cutout = 0.08; }
    else if (layer > 511.5) { layer -= 512.0; cutout = 0.5; }
    if (sky_face && u_has_sky > 0.5) {
        // Skybox-Fläche: dahinter liegt der Himmel
        vec3 sky = sky_color(normalize(v_pos - u_eye));
        f_color = vec4(mix(sky, vec3(1.0, 0.25, 0.2), v_selected * 0.35), 1.0);
        return;
    }
    vec3 n = normalize(v_normal);
    // Zwei feste Lichter, damit jede Seite eines Würfels unterscheidbar bleibt.
    float key = max(dot(n, u_light_dir), 0.0);
    float fill = max(dot(n, normalize(vec3(-0.6, -0.3, 0.2))), 0.0);
    float light = mix(0.38 + 0.5 * key + 0.18 * fill, 1.0, u_flat);
    vec3 base = v_color;
    // Auswahl nur leicht rot färben, damit die Textur sichtbar bleibt (die Kanten sind gelb)
    float tint = 0.45;
    if (u_textured > 0.5 && layer > 0.5) {
        tint = 0.2;
        vec4 texel = texture(u_textures, vec3(v_uv, layer));
        if (texel.a < cutout) discard;
        base = texel.rgb;
        light = mix(0.55 + 0.4 * key + 0.12 * fill, 1.0, u_flat);
    }
    vec3 color = base * light;
    if (u_lit > 0.5 && !marker) {
        color = min(base * preview_light(n), vec3(1.0));
    }
    color = mix(color, vec3(1.0, 0.25, 0.2), v_selected * tint);
    f_color = vec4(color, 1.0);
}
