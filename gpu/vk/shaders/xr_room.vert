#version 450
layout(location = 0) in vec3 pos;
layout(location = 1) in vec2 uv;
layout(push_constant) uniform Push { mat4 clip; } p;
// (centroid: an edge pixel's texture place inside its triangle, not at the pixel's centre past the edge, where the
//  multisampled pass read the next triangle's texels: a bright line along every edge)
layout(location = 0) centroid out vec2 v_uv;

void main() {
    v_uv = uv;
    gl_Position = p.clip * vec4(pos, 1.0);
}
