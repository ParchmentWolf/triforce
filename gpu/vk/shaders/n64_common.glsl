// (Triforce, 11-22) N64 Classic's per-pixel maths for its 3D pass (the plan's step 2, n64_3d.comp): the console's 16-bit
// colour, 5 bits a channel, and its 4 x 4 ordered dither, both on the 240-line grid, not on the screen's pixels. Values are
// display-referred (gamma encoded, 0 to 1), as the console's picture was: the pass encodes before and decodes after.
//
// Written in what GLSL and C++ share (scalar steps, int bit operations, no arrays, no swizzles): tests/test_n64_rules.py
// compiles this file as C++ and runs it on authored values. The rules around it (the presets, the grid's size) are in
// gpu/vk/n64_rules.h.

// (the 4 x 4 Bayer matrix's entry at a grid pixel, 0 to 15: two 2 x 2 steps, the lowest bits of x and y weighed 4 times
// the next ones, so neighbouring pixels are as far apart in the order as they can be. The console's graphics chip offered
// a Bayer matrix and a "magic square" one; at 240 lines through a TV the two cannot be told apart)
int n64_bayer2(int x, int y) { return ((x ^ y) & 1) * 2 + (y & 1); }
int n64_bayer4(int x, int y) { return n64_bayer2(x, y) * 4 + n64_bayer2(x >> 1, y >> 1); }

// (its threshold at grid pixel x, y, centred on 0: -15/32 to +15/32 of one step)
float n64_dither_offset(int x, int y) { return (float(n64_bayer4(x & 3, y & 3)) + 0.5) / 16.0 - 0.5; }

// (one channel kept at `bits` a channel, 0: as it is, dithered by `strength`, 0 none to 1 the full threshold, at grid
// pixel x, y. A value on one of the levels stays on it at any strength; one between two levels comes out as a mix of the
// two over each 4 x 4 cell, in the share of its place between them)
float n64_quantize(float v, int bits, float strength, int x, int y) {
    if (bits <= 0) return v;
    const float levels = float((1 << bits) - 1);
    const float c = clamp(v, 0.0, 1.0);
    const float q = floor(c * levels + 0.5 + n64_dither_offset(x, y) * strength) / levels;
    return clamp(q, 0.0, 1.0);
}

// (the sRGB curve both ways: the picture the 3D pass reads and writes is linear light, the console's was display-referred)
float n64_encode(float v) { return v <= 0.0031308 ? v * 12.92 : 1.055 * pow(v, 1.0 / 2.4) - 0.055; }
float n64_decode(float v) { return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4); }

// (one channel of linear light as the grid keeps it: encoded, kept at `bits` with the dither, decoded. Full colour (bits
// 0) and light above white (HDR's highlights, which no 16-bit picture held anyway) as they are; below black, or not a
// number, black)
float n64_keep(float v, int bits, float strength, int x, int y) {
    if (bits <= 0 || v >= 1.0) return v;
    return n64_decode(n64_quantize(n64_encode(v > 0.0 ? v : 0.0), bits, strength, x, y));
}

// (where an output pixel finds the grid. Its row: the one whose band of the output it is in, every band the same height
// when the sizes divide (1440 output rows, 240 grid rows: 6 each), so the lines have hard edges, as the console's did. Its
// column: a place between two grid pixels, for the video chip's linear resample along the line)
int n64_row(int y, int grid_h, int size_h) {
    const int r = int((float(y) + 0.5) * float(grid_h) / float(size_h));
    return r < grid_h - 1 ? r : grid_h - 1;
}
float n64_column(int x, int grid_w, int size_w) { return (float(x) + 0.5) * float(grid_w) / float(size_w) - 0.5; }
