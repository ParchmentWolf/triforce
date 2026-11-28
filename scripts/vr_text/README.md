# VR's texts and prompts

The texts VR players see in place of the game's: the tutorial pop-ups, the HUD's control hints (their words and icons),
the pause menu's controls page and item captions, one version per VR Control Scheme (Full Gesture and Simplified).

`edits/` holds the team's wording alone. The game's own text is never in it: everything that needs the game's text is
made on each player's PC from their own game, as the button prompts are (`nx2/make_game.py` runs `vr_build.py` after
them, into `<game>/vr_text/gesture` and `/simplified`; `host/mods.c` serves the Control Scheme's while VR is on and none
in flat-screen play, from the game's next start).

## Changing the texts

Edit the files in `edits/` directly: each label is the game's label, and under it only the replacement (`[VR]`,
`[VR2]`) and the icons. Then:

    python vr_build.py <game folder>                into your game, both schemes (restart the game)

To find where a text you saw in the game lives, dump the game's texts on your PC and search them for the exact words:

    python mals_dump.py <game folder>/romfs <a folder outside the repo> USen

The dump names each message file and label; copy that file's name (`# <MSBT>` on a file's first line) and the label into
`edits/`, under the folder its kind goes in (`ui/`, `items/`, `dialogue/`, `other/`; pop-ups and HUD hints in `prompts/`).

`vr_text.py open --game <game folder>` also makes a `work/` folder with the game's text beside yours (never committed),
and `vr_text.py save` takes it back into `edits/` without it, for when reading the original beside yours helps.
`fill_vr_prompts.py` wrote the first pass of the pop-ups, the HUD hints and the controls page from the controls in
`gpu/vk/vk_xr.cpp` (into `work/`, empty fields only).

## How to write

Write yours under `[VR]` (Full Gesture) and `[VR2]` (Simplified):

- An empty `[VR]` keeps the game's text. An empty `[VR2]` takes the `[VR]` one. `<game>` keeps the game's own for that
  scheme (`save` writes it for a text that is the game's word for word).
- Every file replaces the game's text, except `items/PouchContent.txt` (item names and captions): there your text is
  added under the game's own, an empty line between.
- Line breaks: break the line; the game breaks at about 50 characters, three lines to a box. Item captions have no
  second box (`{0.4:}` does nothing there) and show about six lines.
- Button icons in running text: `[A] [B] [X] [Y] [L] [R] [ZL] [ZR] [Plus] [Minus] [LS] [RS] [Up] [Down] [Left] [Right]`,
  `[LS_Up] [LS_Down] [LS_Left] [LS_Right] [LS_LeftRight] [RS_UpDown] [RS_LeftRight]`. In VR every one of them shows the
  VR control that presses that button (`nx2/prompt_vr.py` MAP).
- Tags as the game's texts have them: `{0.3:0000}`...`{0.3:ffff}` a highlight, `{0.2:7d00}` larger text, `{5.0:}`
  `{5.1:}` `{5.2:}` pauses; keep the `{2.x:...}` `{201.x:...}` `{3.0:...}` `{4.0:...}` tags of a line as they are.

## Prompts

- `prompts/hud_hints/`: each HUD hint set, one step per button. `[VR]` is the word: one word is shared by every set
  that shows it (`vr_text.py open` lists them as `[Shared with]`), and a step without a word of its own in the game shows its icon alone.
  `[VR icon]` is the icon that step shows in VR (the build changes that step's key in the hint table).
- `prompts/tutorial_popups/`: `Title_` the heading, `Msg_` the line, `Guide_..._00/_01/_02` the words beside each step's
  icon. The game's code chooses those icons by button, so in VR they follow the VR control of that button.
- Icon names: `L_Grip R_Grip L_Trigger R_Trigger Swing Menu`, the game's buttons (`A B X Y Plus Minus ...`),
  `LS_Click RS_Click` (a stick pressed in), `-` (no icon: a gesture of the body).

The VR icons themselves are drawn into the game's icon font at build time (`nx2/prompt_vr.py`): the triggers and grips
from the game's own L, R, ZL and ZR with their letters cut anew, the swing and the Menu from `icons/` (the swing's outline
comes from `icons/swing_icon_source.py`).

## The other tools

`mals_dump.py` (every message of a language as text), `mals_edit.py` (a message archive with texts replaced),
`ctrlguide.py` (the HUD hint table by names), `byml_dump.py`, `evfl_params.py`, `inspect_romfs.py`, `gen_vr_text.py`
(the readable files `open` uses). `BRIEF.md` has how the game keeps its texts, its icons and its prompts.
