// (Triforce, 11-22) N64 Classic's TV, per pixel (n64-classic-mode-plan.md, step 4; shaders/n64_tv.comp): the beam across a
// TV line, the phosphor mask, the composite signal's colour, the vignette and the screen's curve. Written in what GLSL and
// C++ share (scalar steps, int operations, no arrays, no swizzles): tests/test_n64_tv.py compiles this file as C++ and runs
// it on authored values. Light is linear here unless a name says otherwise; the composite steps take the encoded signal.

// ---- the beam ----

// (its width, in TV lines (one sigma), from the light it draws, 0 to 1: a dim line is thin, a bright one swells into the gap
// beside it, as a tube's spot grew with its current)
float n64_beam_sigma(float level) { return 0.18 + 0.22 * clamp(level, 0.0, 1.0); }
// (the beam's light at f TV lines from the line's middle, -0.5 to 0.5, of its peak)
float n64_beam(float f, float level) {
    const float s = n64_beam_sigma(level);
    return exp(-f * f / (2.0 * s * s));
}
// (the mean of n64_beam over a whole line: sigma * sqrt(2 pi) * erf(0.5 / (sigma sqrt 2)), erf by its closed approximation
// (Winitzki's, a = 0.147), within a thousandth here)
float n64_beam_mean(float level) {
    const float s = n64_beam_sigma(level);
    const float x = 0.5 / (s * 1.41421356);
    const float x2 = x * x;
    const float erf = sqrt(1.0 - exp(-x2 * (1.27323954 + 0.147 * x2) / (1.0 + 0.147 * x2)));
    return s * 2.50662827 * erf;
}
// (what a channel of light `level` is multiplied by at f lines from its line's middle, with the scanlines at `strength`, 0 to
// 1: the gap darkened that much, and seven tenths of the light the gap took given back to the line, so a picture keeps most
// of its brightness and bright lines bloom. 1 everywhere at strength 0)
float n64_scan(float f, float level, float strength) {
    const float k = clamp(strength, 0.0, 1.0);
    const float beam = n64_beam(f, level);
    const float back = 1.0 / n64_beam_mean(level);
    return (1.0 + k * (beam - 1.0)) * (1.0 + 0.7 * k * (back - 1.0));
}

// ---- the mask ----

// (which of red, green and blue (channel 0, 1, 2) a window pixel's phosphor shows, 1, or not, 0. type: 2 aperture grille
// (stripes), 3 slot mask (stripes broken every 4 rows, the breaks of neighbouring triads 2 rows apart), 4 shadow mask (dots,
// alternate rows half a triad apart); anything else, every channel)
float n64_mask_lit(int x, int y, int type, int channel) {
    if (type == 2) return x % 3 == channel ? 1.0 : 0.0;
    if (type == 3) {
        const int row = (y + ((x / 3) % 2) * 2) % 4;
        return row != 0 && x % 3 == channel ? 1.0 : 0.0;
    }
    if (type == 4) return (x + (y % 2) * 2) % 3 == channel ? 1.0 : 0.0;
    return 1.0;
}
// (what a channel is multiplied by there: an unlit phosphor darkened by `strength`, 0 to 1, and the mask's mean darkening
// half given back, so the picture dims only a little with it)
float n64_mask(int x, int y, int type, int channel, float strength) {
    const float k = clamp(strength, 0.0, 1.0);
    if (type < 2 || type > 4 || k <= 0.0) return 1.0;
    const float lit = n64_mask_lit(x, y, type, channel);
    const float mean_dark = type == 3 ? k * 3.0 / 4.0 : k * 2.0 / 3.0;   // (a channel lit on a quarter of a slot mask, a third of the others)
    return (1.0 - k + k * lit) / (1.0 - 0.5 * mean_dark);
}

// ---- the composite signal (on the encoded picture, as the cable carried it) ----

float n64_y(float r, float g, float b) { return 0.299 * r + 0.587 * g + 0.114 * b; }
float n64_i(float r, float g, float b) { return 0.595716 * r - 0.274453 * g - 0.321263 * b; }
float n64_q(float r, float g, float b) { return 0.211456 * r - 0.522591 * g + 0.311135 * b; }
float n64_red(float y, float i, float q) { return y + 0.9563 * i + 0.6210 * q; }
float n64_green(float y, float i, float q) { return y - 0.2721 * i - 0.6474 * q; }
float n64_blue(float y, float i, float q) { return y - 1.1070 * i + 1.7046 * q; }
// (the weight of tap t, -2 to 2, of the colour's sideways blur: 1, 2, 3, 2, 1 of 9)
float n64_bleed_weight(int t) { return (3.0 - float(t < 0 ? -t : t)) / 9.0; }

// ---- the screen ----

// (a coordinate across the screen, -1 to 1, to where the picture is under it on a screen curved by `curve` (its barrel at
// the corners), given the other coordinate: pushed outward the more the further from the middle, so the picture's corners
// fall off the screen, which is black there)
float n64_warp(float a, float other, float curve) { return a * (1.0 + curve * (a * a + other * other)); }
// (the light at a place of the picture, u and v 0 to 1: the corners darker, the more the more the screen is curved; 1
// everywhere on a flat one)
float n64_vignette(float u, float v, float curve) {
    const float amount = clamp(curve * 15.0, 0.0, 0.6);
    const float edge = clamp(16.0 * u * v * (1.0 - u) * (1.0 - v), 0.0, 1.0);
    return 1.0 - amount * (1.0 - sqrt(sqrt(edge)));
}
// (the rounded corner's light at a place of the warped picture, a and b -1 to 1: 1 inside, falling to 0 over the corner's
// edge; a corner's radius is a 30th of the picture on a curved screen, none on a flat one)
float n64_corner(float a, float b, float curve) {
    if (curve <= 0.0) return 1.0;
    const float r = 1.0 / 15.0;
    const float da = max(abs(a) - (1.0 - r), 0.0), db = max(abs(b) - (1.0 - r), 0.0);
    const float d = sqrt(da * da + db * db) / r;
    return clamp((1.0 - d) * 8.0, 0.0, 1.0);
}
