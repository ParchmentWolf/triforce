/* (Triforce) The Output resolution row's sizes and the picture they give, for host/nn_applet.c (the game's output at the
   start), host/hos_main.c (the widescreen picture) and gpu/vk/vk_menu.cpp (the rows). One rule for every size:

     The Output resolution is the picture's size. The game's own frame (its HUD, menus and story movies) is 16:9 at that height.
     A size of another shape is a wider or a narrower picture of exactly that size: the world fills it, and the frame
     keeps its 16:9 shape in its middle (a narrower one: its whole width). A 16:9 size takes its shape from the Ultrawide
     row instead (gpu/vk/ultrawide_rows.h), at the same height.

   So 3840 x 1600 is the frame 2848 x 1600 in the picture 3840 x 1600, a 12:5 screen pixel for pixel, and the Ultrawide
   row has nothing to choose there: it shows the size's shape.

   0 to 6 are fixed sizes, numbered as they were added so that a saved number keeps its size: 0 the game's 2048 x 1152,
   1 2560 x 1440, 2 3840 x 2160, 3 1920 x 1080, 4 5120 x 1440 (32:9), 5 5120 x 2880, 6 5120 x 2160 (21:9). Then:
    - 9 Custom: any size, output_width= and output_height= in triforce_options.ini (the Output width and Output height
      rows, 2560 x 1440 until they are set), or HOS_OUTPUT_SIZE=<w>x<h> over them.
      The menu's row lists the size of every connected screen by the monitor's name (host/hos_screens.h), and choosing one
      is choosing Custom with that size: what is saved is a size, never a screen's place among those connected, so the same
      file gives the same picture at the next start whichever screens are there, and a size whose screen is gone is shown
      as Custom. A screen of a fixed size is that fixed choice.
    - 8 Screen: the size of the screen the game's window opens on, read at the start. What an options file from before
      the screens were listed has, and HOS_OUTPUT_RES=8; it means what it meant, and the menu saves it as that size.

   Before options_version 8 the two fixed sizes that are not 16:9 were the game's frame itself: its 16:9 cameras and HUD
   stretched over it unless the Ultrawide row was set to the same shape, and with another shape the row's picture at that
   height. output_res_read keeps such a file's picture.

   Plain C: the host's C and the renderer's C++ both take it. */
#ifndef OUTPUT_SIZES_H
#define OUTPUT_SIZES_H

#include <math.h>

#define OUTPUT_FIXED_N 8
#define OUTPUT_SCREEN 8
#define OUTPUT_CUSTOM 9
#define OUTPUT_LAST 9
#define OUTPUT_OPTIONS_VERSION 9   /* (stock 0.6 and native 0.5.2 migrate to this distinct schema) */

/* A size from outside keeps its shape, within what the picture takes (5:4 to 48:9, output_picture), and is brought into
   these limits in that shape: no side past its end, and at most 5120 x 2880's pixels. The game's render targets come from a
   pool scaled with the picture's pixels and kept to 900 MB, the most known to pass the game's own reservation at boot
   (host/nn_applet.c hos_rt_pool_size); 5120 x 2880 (14.7 million pixels) is the largest picture that booted and played
   with it. So 7680 x 4320 is 5120 x 2880, and 10000 x 5000 is 5424 x 2712: smaller, never another shape. */
#define OUTPUT_MIN_W 640
#define OUTPUT_MIN_H 360
#define OUTPUT_MAX_W 7680
#define OUTPUT_MAX_H 2880
#define OUTPUT_MAX_PIXELS (5120.0 * 2880.0)
/* A shape from the Ultrawide row or HOS_ASPECT at a 16:9 size: the picture kept to 3840 x 2160's pixels, as before (a 32:9
   picture at the 4K output was 7680 x 2160, and the game crashed as Kokiri Forest loaded, issue 1031: 5400 x 1520 there) */
#define OUTPUT_ROW_PIXELS (3840.0 * 2160.0)
#define OUTPUT_SHAPE_MIN (5.0 / 4.0)
/* ((Triforce) 11-24) up to 48:9, three 16:9 screens side by side (7680 x 1440, 5760 x 1080), which a screen's size or
   Custom of that shape is now: it was kept to 32:9, the picture between black bars there */
#define OUTPUT_SHAPE_MAX (48.0 / 9.0)

/* The fixed size v's width or height (v 0 to 6) */
static inline unsigned output_fixed_size(int v, int height) {
    static const unsigned wh[OUTPUT_FIXED_N][2] = {{2048, 1152}, {2560, 1440}, {3840, 2160}, {1920, 1080},
                                                   {5120, 1440}, {5120, 2880}, {5120, 2160}, {1536, 864}};
    if (v < 0 || v >= OUTPUT_FIXED_N) v = 0;
    return wh[v][height ? 1 : 0];
}

/* The game's 16:9 frame at that height: its width the nearest whole multiple of 8 pixels (1600: 2848) */
static inline unsigned output_frame_width(unsigned height) { return (height * 16u + 36u) / 72u * 8u; }

/* Whether a shape, width over height, is the game's own 16:9 (within 1%: 1366 x 768 is) */
static inline int output_shape_is_game(double shape) {
    const double game = 16.0 / 9.0;
    return !(shape > game * 1.01 || shape < game * 0.99);
}

/* Whether a size has a shape of its own, not the game's 16:9: such a size is a wider or narrower picture by itself, and
   the Ultrawide row does not apply to it */
static inline int output_size_shaped(unsigned w, unsigned h) { return w && h && !output_shape_is_game((double)w / (double)h); }

/* "<w>x<h>" (HOS_OUTPUT_SIZE): 1 and the two sides, or 0 when it is not that */
static inline int output_parse_size(const char *s, long *w, long *h) {
    long v[2] = {0, 0};
    int i = 0;
    if (!s) return 0;
    for (;; s++) {
        if (*s >= '0' && *s <= '9') {
            if (v[i] > 100000) return 0;
            v[i] = v[i] * 10 + (*s - '0');
        } else if ((*s == 'x' || *s == 'X') && i == 0 && v[0] > 0) {
            i = 1;
        } else if (*s == 0 && i == 1 && v[1] > 0) {
            *w = v[0], *h = v[1];
            return 1;
        } else {
            return 0;
        }
    }
}

/* (output_size_used) The widths, whole multiples of 8, that a picture of height h can have on one side of 16:9 (wide: wider
   than it, else narrower): those whose shape is within 5:4 to 48:9 and outside the 1% beside 16:9, within the width's ends
   and the pixels. *lo > *hi: none at that height */
static inline void output_width_range(unsigned h, int wide, unsigned *lo, unsigned *hi) {
    const double game = 16.0 / 9.0, edge = (double)h * game * (wide ? 1.01 : 0.99);
    double least = wide ? floor(edge / 8.0) * 8.0 + 8.0 : ceil((double)h * OUTPUT_SHAPE_MIN / 8.0) * 8.0;   /* (past the edge) */
    double most = wide ? floor((double)h * OUTPUT_SHAPE_MAX / 8.0) * 8.0 : ceil(edge / 8.0) * 8.0 - 8.0;      /* (short of it) */
    const double pixels = floor(OUTPUT_MAX_PIXELS / (double)h / 8.0) * 8.0;
    if (least < OUTPUT_MIN_W) least = OUTPUT_MIN_W;
    if (most > OUTPUT_MAX_W) most = OUTPUT_MAX_W;
    if (most > pixels) most = pixels;
    *lo = (unsigned)least, *hi = most < 0 ? 0 : (unsigned)most;
}

/* A size from outside as the game takes it: 0 when there is none (a side 0 or less); else 1 and the size in its own shape
   (kept to 5:4 to 48:9) within the limits above: made smaller in that shape where a side or the pixels are past them, larger
   where a side is under its least. Its width is a whole multiple of 8 pixels (as every picture's), its height too where it
   was made smaller, and a shape within 1% of 16:9 is the game's own frame at that height. The shape is taken first: clamping
   each side by itself would change it (7680 x 4320 would come out 2.67:1).
   What comes out is the picture, pixel for pixel, and is taken as itself when given again (the menu saves it and the host
   reads it back). That holds by how the width is chosen, not by trying again: the width is the multiple of 8 nearest the
   shape's among those output_width_range allows at that height, so the size that comes out keeps every limit and its side of
   16:9; given again, nothing makes it smaller or larger, its height stays, and its own width is the nearest to its shape.
   Rounding the width alone to the nearest 8 did not have that: at an end of the shapes it could pass the end, and beside
   16:9 it could fall into the 1% (tests/test_output_resolution.py goes through sizes) */
static inline int output_size_used(long w, long h, unsigned *out_w, unsigned *out_h) {
    if (w <= 0 || h <= 0) return 0;
    double shape = (double)w / (double)h;
    if (shape > OUTPUT_SHAPE_MAX) shape = OUTPUT_SHAPE_MAX;
    if (shape < OUTPUT_SHAPE_MIN) shape = OUTPUT_SHAPE_MIN;
    if (output_shape_is_game(shape)) {   /* (16:9 fits every limit at a height within its own) */
        const unsigned uh = (unsigned)(h < OUTPUT_MIN_H ? OUTPUT_MIN_H : h > OUTPUT_MAX_H ? OUTPUT_MAX_H : h);
        *out_w = output_frame_width(uh), *out_h = uh;
        return 1;
    }
    const int wide = shape > 16.0 / 9.0;
    double fh = (double)h, scale = 1.0;
    const double fw = fh * shape;
    if (fh * scale > OUTPUT_MAX_H) scale = OUTPUT_MAX_H / fh;
    /* ((Triforce) 11-24: half a pixel of room, so that a size this made at the width's end (shapes past 32:9 reach it below
       2160 lines) is taken as itself again: its width over its height times its height is not 7680 to the last bit) */
    if (fw * scale > OUTPUT_MAX_W + 0.5) scale = OUTPUT_MAX_W / fw;
    if (fw * fh * scale * scale > OUTPUT_MAX_PIXELS) scale = sqrt(OUTPUT_MAX_PIXELS / (fw * fh));
    unsigned uh, lo, hi;
    if (scale < 1.0) {   /* (smaller, in its shape: the height a whole multiple of 8 as well) */
        uh = (unsigned)(fh * scale / 8.0) * 8u;
    } else {
        if (fh < OUTPUT_MIN_H) fh = OUTPUT_MIN_H;
        if (fh * shape < OUTPUT_MIN_W) fh = OUTPUT_MIN_W / shape;
        uh = (unsigned)ceil(fh);
    }
    output_width_range(uh, wide, &lo, &hi);
    /* (no width at that height: a shape just wider than 16:9 at the most pixels, where the first width past the 1% is over
       them, by 8 at most. 8 lines fewer make room: there the pixels then allow about 14 more of width, and the 1% is about
       14 nearer) */
    if (lo > hi) uh = (uh - 1u) / 8u * 8u, output_width_range(uh, wide, &lo, &hi);
    unsigned uw = (unsigned)((double)uh * shape / 8.0 + 0.5) * 8u;
    if (uw < lo) uw = lo;
    if (uw > hi) uw = hi;
    *out_w = uw, *out_h = uh;
    return 1;
}

/* output_width= and output_height= as an options file has them (0: no line), for Custom's size: a side that is not a size
   (no line, 0 or less) is the row's default, 2560 and 1440. The host and the menu read the file's two numbers through this
   and output_size_used, so a size written past the rows' ends keeps its shape for both */
static inline void output_custom_read(long *w, long *h) {
    if (*w <= 0) *w = 2560;
    if (*h <= 0) *h = 1440;
}

/* The picture for the game's frame of height frame_h and a shape want, width over height: 0 for the game's own 16:9 picture
   (want 0, 1 or less, or within 1% of 16:9), else 1 and its size, whole multiples of 8 pixels wide. The shape is kept to
   5:4 to 48:9. sized: the shape is the Output resolution's own (frame_h its height, want its width over its height), and the
   picture is that size; otherwise the shape is the Ultrawide row's or HOS_ASPECT's, and a picture of more than
   3840 x 2160's pixels is made smaller in its shape */
static inline int output_picture(unsigned frame_h, double want, int sized, unsigned *out_w, unsigned *out_h) {
    if (!(want > 1.0) || output_shape_is_game(want)) return 0;
    const double r = want > OUTPUT_SHAPE_MAX ? OUTPUT_SHAPE_MAX : want < OUTPUT_SHAPE_MIN ? OUTPUT_SHAPE_MIN : want;
    const double most = sized ? OUTPUT_MAX_PIXELS : OUTPUT_ROW_PIXELS;
    unsigned oh = frame_h, ow = (unsigned)(oh * r / 8 + 0.5) * 8;   /* (whole multiples of 8 pixels) */
    if ((double)ow * oh > most) {
        oh = (unsigned)(sqrt(most / r) / 8) * 8;
        ow = (unsigned)(oh * r / 8) * 8;
    }
    *out_w = ow, *out_h = oh;
    return 1;
}

/* output_res= as an options file holds it, with the file's options_version and its Ultrawide row (as ultrawide_row_read
   gives it). Before version 8, 4 (5120 x 1440) and 6 (5120 x 2160) were the game's frame: with the row on another shape
   than theirs the picture was the row's at their height, which the 16:9 size of that height (1, 2560 x 1440, and 2,
   3840 x 2160) gives with the same row. With the row on their own shape the picture was theirs, as it is now; with the row
   on 16:9 the 16:9 picture was stretched over them, and is now theirs too */
static inline int output_res_read(int v, int version, int ultrawide_row) {
    if (version >= 8) return v;
    if (v == 4 && ultrawide_row != 0 && ultrawide_row != 3) return 1;
    if (v == 6 && ultrawide_row != 0 && ultrawide_row != 2) return 2;
    return v;
}

/* Stock 0.6 and the native 0.5.2 branch both wrote version 8. The native writer
   always wrote Custom's size fields, even under a fixed output. Before 8, stock
   had no output 7/8. Call before clamping the saved value or migrating handheld. */
static inline int output_legacy_file(int version, int size_fields) {
    return version < 8 || (version == 8 && size_fields);
}
static inline int output_file_read(int v, int version, int row, int size_fields) {
    if (version >= OUTPUT_OPTIONS_VERSION) return v;
    const int legacy = output_legacy_file(version, size_fields);
    v = output_res_read(v, legacy ? version : 7, row);
    if (legacy && v >= 7 && v <= 8) return v + 1;
    return v;
}
#endif
