// Himmel wie im Spiel: sechs Bilder (rt, lf, bk, ft, up, dn) als Ebenen 0..5, Zuordnung
// von Richtung zu Bild und Bildkoordinate nach der Skybox-Tabelle der Engine.
uniform sampler2DArray u_sky;
vec3 sky_color(vec3 d) {
    vec3 a = abs(d);
    float layer;
    vec2 st;
    if (a.x >= a.y && a.x >= a.z) {
        if (d.x > 0.0) { layer = 0.0; st = vec2(-d.y, d.z) / a.x; }
        else           { layer = 1.0; st = vec2(d.y, d.z) / a.x; }
    } else if (a.y >= a.z) {
        if (d.y > 0.0) { layer = 2.0; st = vec2(d.x, d.z) / a.y; }
        else           { layer = 3.0; st = vec2(-d.x, d.z) / a.y; }
    } else {
        if (d.z > 0.0) { layer = 4.0; st = vec2(-d.y, -d.x) / a.z; }
        else           { layer = 5.0; st = vec2(-d.y, d.x) / a.z; }
    }
    vec2 uv = vec2((st.x + 1.0) * 0.5, (1.0 - st.y) * 0.5);
    // Rand eines Halbpixels freilassen, sonst blitzen die Nachbarkanten durch
    uv = clamp(uv, vec2(0.001), vec2(0.999));
    return texture(u_sky, vec3(uv, layer)).rgb;
}
