#version 450
layout(binding = 0) uniform sampler2D picture;
layout(location = 0) centroid in vec2 v_uv;   // (xr_room.vert: inside the triangle at its edges)
layout(location = 0) out vec4 colour;

void main() {
    const vec4 c = texture(picture, v_uv);
    if (c.a < 0.5) discard;   // (a cut-out surface's clear part: the hanging plants, the leaves; the rest is solid)
    colour = vec4(c.rgb, 1.0);
}
