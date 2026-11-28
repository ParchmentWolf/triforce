# Triforce: where the game keeps its texts and button prompts, and how to override them

Applies to the supported game (build `e0f3ccfa`) under Triforce v0.8.3 and the `vr-support` branch (66a85c23). Everything below
was read from the game's own files or seen on screen in test runs on a copy of the game. The tools in `tools/` read your own
RomFS. No game text is included here beyond a few words to identify a line.

**Short version**
- Every text is in `romfs/Mals/<Lang>.Product.110.sarc.zs`: one archive per language holding 540 MSBT files.
- A RomFS mod can replace that archive. `tools/mals_edit.py` writes the mod from a list of label → new text. Your text can
  be longer than the game's, because Triforce gives a mod's file the room it needs. This was tested.
- To put a button icon in running text (dialogue, captions, banners) use the game's icon tag `{1.4:NN}`; `mals_edit.py`
  writes it for `[ZL]`, `[A]` and so on. A raw icon code point such as U+E046 shows as an empty box in running text.
- All button icons come from one font: `Font2/Scalable/External`. Triforce builds one copy per controller face and swaps
  icons per binding at run time. To slot in new icons, give a face new glyphs, or add a face (section 5).

Pictures:
- `text-override-test.jpg`: a mod's texts on screen, with the icon tag and with a raw code point.
- `icon-tag-values.jpg`: what each `{1.4:NN}` value draws.

---

## 1. Where the text is

| What | Where |
|---|---|
| Messages | `romfs/Mals/<Lang>.Product.110.sarc.zs`, 16 languages (USen, EUen, USfr, EUfr, USes, EUes, USpt, EUde, EUit, EUnl, EUpl, EUru, JPja, KRko, CNzh, TWzh). zstd with the `zs.zsdic` dictionary from `Pack/ZsDic.pack.zs`, then a SARC. |
| Inside | 540 MSBT files, the same names and labels in every language (21,138 texts in each). All UTF-8. |
| Which language Triforce shows | `language.txt` in the game folder (`en-US` → USen, `en-GB` → EUen, `fr` → EUfr, `fr-CA` → USfr, `de`, `it`, `es` → EUes, `es-419` → USes, `pt-BR` → USpt, `nl`, `pl`, `ru`, `ja`, `ko`, `zh-Hans` → CNzh, `zh-Hant` → TWzh); `HOS_LANGUAGE` overrides it. |
| Who says what | `romfs/Event/EventFlow/<Flow>.bfevfl.zs`. A flow refers to its lines as `EventFlowMsg/<File>:<Label>`, and opens a tutorial pop-up with an `ActionGuideType` number (section 3D). |

The folders inside the archive:

| Folder | Files | What |
|---|---|---|
| `EventFlowMsg/` | 454 | NPC talk (`Npc_<Race>_<NNN>_<Child/Adult>.msbt`), cutscenes (`Dm_*`), Navi (`NaviChat`, `NaviHint`, `NaviHint_Enemy`, `NaviTips`), signs (`SignboardWood`), shops, minigames |
| `LayoutMsg/` | 40 | UI texts by layout: `ActionGuide_00` (tutorial pop-ups), `CtrlGuide_00` (HUD control hints), `DoCommand_00` (the action word: Talk, Open, Check…), `PlusMenu_00` (pause menu, Basic Controls page), `SystemOption_00`, `Title_00`… |
| `ActorMsg/` | 4 | `PouchContent` (item names; `<Item>_GetMessage`, `_GetCaption`, `_SecondGetCaption` when you get one), `Enemy`… |
| `StaticMsg/` | 3 | `GuideKeyIcon` (each button name → its icon character), `Reference`, `GrammarArticle` |
| `LocationMsg/` | 1 | `Location`: area names (the banner when you enter an area) |
| `ChallengeMsg/`, `NpcTerrorMsg/`, `StaffRollMsg/` | 20, 16, 2 | Quest log, reactions, credits |

**MSBT text.** Text is UTF-8 with inline tags: byte `0x0E`, then u16 group, u16 type, u16 size, then the parameters. An end
tag is `0x0F`, then u16 group and u16 type. `tools/mals_dump.py` writes tags as `{g.t:hex}`. The ones you need for new
text:

| Tag | Effect |
|---|---|
| `{0.3:0000}` … `{0.3:ffff}` | Highlight colour on, then back to the default (`0100` is a second colour) |
| `{0.4:}` | Next box (the player presses A) |
| `{0.2:7d00}` | Text size in percent (`7d00` = 125%, `5000` = 80%) |
| `{1.4:NN}` | A button icon: see 3A |
| `{3.0:…}`, `{4.0:…}` | At the start of NPC lines: presumably the speaker's face and animation (the animation by name). Keep them as the original line has them. |
| `{5.0:}`, `{5.1:}`, `{5.2:}` | Pauses while the text types out |
| `{2.x:…}`, `{201.x:}` | Values from the game (item name, price) and grammar (articles, plurals). Keep as found. |

The game's texts break their lines by hand with `\n`, at about 50 characters, three lines to a box. Do the same in your
text.

## 2. The tutorial texts you asked about

These are the Kokiri Forest ones, from the event flows. *Guide* is the tutorial pop-up the flow opens; its number is the
`ActionGuideType` (3D).

| Who | Flow | Its lines | Guide it opens |
|---|---|---|---|
| Kokiri girl on the shop's roof ("Up here!") | `Npc_Kokiri_011_Child` | `EventFlowMsg/Npc_Kokiri_011_Child.msbt` (43 labels in the flow) | 12 `LockOn` (Target) |
| The "swordsman" kid at the training grounds, by the scarecrows | `Npc_Kokiri_006_Child` | `EventFlowMsg/Npc_Kokiri_006_Child.msbt` (118 labels; e.g. `Talk_0004`, `Talk_80`, `Talk_65`, `Talk_14`, `Talk_110`–`Talk_120`) | 55 `LockOnSideMove`, 6 `SideJump`, 7 `Backflip`, 4 `JumpSlash` |
| Kid at the training grounds who teaches the shield on the scarecrow | `Npc_Kokiri_010_Child` | `EventFlowMsg/Npc_Kokiri_010_Child.msbt` (50) | 46 `LockOnShield` (Raise Shield) |
| Kid who teaches the map | `Npc_Kokiri_003_Child` | `EventFlowMsg/Npc_Kokiri_003_Child.msbt` (48) | 11 `SystemMinus` (Map) |
| Kokiri shop clerk (Deku Shield) | `DisplayShop` | `EventFlowMsg/Npc_Kokiri_001_Shop_Child.msbt`: `Shop_07*` (bought), `Shop_31`–`33` (one shield only), `Talk_0100`–`0103` (lost shield). | See note below. |
| Saria | `Npc_Kokiri_Saria_Child` (+ `_SacredForestMeadow`) | `EventFlowMsg/Npc_Kokiri_Saria_Child.msbt` (71 labels in the flow), cutscenes `Dm_Kokiri_*`, `Dm_MelodyGet_Saria` | None: she gives directions (to the training grounds, for example) but opens no guide. |
| Message board ("Adventurer's Guide") | `Obj_Kokiri_MessageBoard_A_01` | `EventFlowMsg/SignboardWood.msbt`, by label: `KokiriForest_018` (all Kokiri signs are `KokiriForest_0NN`) | 43 `Save` (System Menu) |
| Sign by the tree you roll into | `Obj_Kokiri_Signboard_GuideAction_A_02` | `SignboardWood` `KokiriForest_022`, plus Navi's `EventFlowMsg/Get_StoneOfForest.msbt` `NaviTalk_01`/`02` | 20 `RollAttack` |
| Navi | `NaviHint`, `NaviTips`, `NaviChat` | `EventFlowMsg/NaviHint*.msbt`, `NaviTips`, `NaviChat` | 14 `Navi`, 56 `Weapon_Shield_Hylian` |

Shop clerk note:
- Buying the Deku Shield shows its get message and caption: `ActorMsg/PouchContent.msbt`
  `Weapon_Shield_Deku_GetMessage` / `_GetCaption`. The Deku Shield has no guide of its own; the lesson is the shield kid
  above.
- After a purchase, the `ActionGuide` flow's `ActionGuideForShop` opens 52 `EquipmentMenu`, or 44/45 for a mask or
  boots. This applies to items that have a guide, such as the Hylian Shield.

**Items when you first get one.**
- The message and caption are `ActorMsg/PouchContent.msbt` `<actor>_GetMessage` / `_GetCaption`, and
  `_SecondGetCaption` for later ones.
- Which guide follows is the item's `ActionGuideType` in `RSDB/PouchActorInfo.Product.111.rstbl.byml.zs`:

| Items | Guide |
|---|---|
| Kokiri Sword | `AttackByWeapon` (0) |
| Fairy Slingshot | `SlingShot` |
| Deku Stick | `DekuStick` |
| Deku Nut | `DekuNut` |
| Bombs | `Bomb` |
| Boomerang | `Boomerang` |
| Bow | `Bow` |
| Hookshot | `Hookshot` |
| Megaton Hammer | `Hammer` |
| Bottles | `Bottle` |
| Masks | `HeadShortcut` |
| Boots | `BootShortcut` |
| Tunics, Hylian and Mirror Shields, Biggoron's Sword | `EquipmentMenu` |
| Goron's Bracelet | `GoronGauntlet` |

The guide's own texts are in `LayoutMsg/ActionGuide_00.msbt` (3D).

## 3. Button prompts: four places

### A. Icons in running text: the `{1.4:NN}` tag

The game puts icons inside its sentences with group 1, type 4, and a one-byte value. Examples:
- `SystemOption_00` `LockOnType_Caption`: "Target while holding `{1.4:0f}`".
- The shop lines `{1.4:2d} ZELDA NOTES?`.

What each value draws, seen on screen (`icon-tag-values.jpg`, Switch face, default options):

| NN | Icon | NN | Icon | NN | Icon |
|---|---|---|---|---|---|
| 00–03 | Left stick up, down, left, right | 0a | A | 17 | Plus |
| 04, 05 | Right stick up/down, left/right | 0c | X | 18 | Minus |
| 06–09 | D-pad up, down, left, right | 0d | Y | 19–20 | Arrows: right, left, up, down, up-right, up-left, down-left, down-right |
| 0f | ZL | 10 | B | 21, 22 | Left stick, right stick |
| 14, 15 | L, R | 16 | ZR | 23 | Left stick left/right |
| 24 | The console | 2d | ZELDA NOTES logo | | |

- 0b and 0e also draw A and ZL; 11–13 and 27 draw B; 25, 26 and 28 draw X. These are variants, and some may follow the
  control options, such as the jump-button swap. The game's own captions use 0f, 17, 27 and 28.
- **Triforce re-draws these per controller.** With the keyboard face, `{1.4:0f}{1.4:17}{1.4:27}{1.4:28}` showed the keys
  bound to ZL, Plus, B and X (Z, Tab, Shift, Space), in the title menu and in the area banner.
- **A raw code point is not an icon in running text.** U+E040/E046/E043 written straight into the title's text showed
  empty boxes. Use the tag. `mals_edit.py` turns `[ZL]`, `[A]` and the like into these tags.

### B. Icon panes (the icon character as the whole text)

- Small panes in the layouts draw their text with the icon font, so their texts are just the character. For example:
  - `LayoutMsg/DoCommand_00` `T_KeyA_00` = U+E040;
  - `PlusMenu_00` `…-T_IconL_00` / `T_IconR_00`.
- The code looks icons up by name in `StaticMsg/GuideKeyIcon.msbt` (A, B, X, Y, L, R, ZL, ZR, Plus, Minus, the D-pad
  directions, LS_/RS_ directions, Push, Shake):
  - A, B, X, Y = U+E040–E043;
  - L, R, ZL, ZR = E044–E047;
  - Plus E04B, Minus E04C;
  - LS/RS push E056/E057;
  - D-pad up/down/left/right E060–E063;
  - UpDown E064, LeftRight E065, all four E049;
  - stick directions E050–E05F;
  - RS_Shake E068.

### C. The HUD control hints

- The words are in `LayoutMsg/CtrlGuide_00.msbt` (Move, Jump, Swing Sword, Target, Throw, Shoot Arrow…).
- Which button shows beside each is in `UI/CtrlGuideSetTable/CtrlGuideSetTable.game__ui__CtrlGuideSetTable.bgyml`. Its
  `GuideType`, `Command` and `GuideKey` are murmur3 (seed 0) hashes of names; `tools/ctrlguide.py` prints it with the
  names. Default controls:

| Command | Button |
|---|---|
| Target | ZL |
| Swing Sword | Y |
| Jump | `X_OptionB` (X, or B with the option) |
| Let Go / Put Away | `B_OptionX` |
| Items (throw, shoot, swing a stick…) | ZR |
| Change View, Move Shield | RS |
| Navi | D-pad right |
| Item pouch | Plus |
| Horse | Whoa: LS down; Dismount: B |

- The table's keys are GuideKeyIcon names, so its icons are the font's. They follow Triforce's faces.

### D. The tutorial pop-ups (Action Guides)

- Texts: `LayoutMsg/ActionGuide_00.msbt`:
  - `Title_<Type>` (heading);
  - `Msg_<Type>` (one line);
  - `Guide_<Type>_00`…`_02` (one word or so per step, each beside a button icon);
  - `Guide_Legacy_*` (the steps for the classic control type).
- The icon beside each step is chosen by the game's code for that type. There is no table of it in the RomFS. It is drawn
  from the icon font, so it follows Triforce's faces.
- To change what a step says, override its `Guide_` text. To change which button it shows, you would need a code change.
- `ActionGuideType`, the number the flows pass (from the game's own list of names):

```
 0 AttackByWeapon      1 HorizontalSlash     2 VerticalSlash      3 Thrust             4 JumpSlash
 5 RotarySlash         6 SideJump            7 Backflip           8 Ocarina            9 SelectItem
10 SystemPlus         11 SystemMinus        12 LockOn            13 SlingshotAndBow   14 Navi
15 Melody             16 ItemShortcut       17 NaviAdvice        18 Amiibo            19 OcarinaPlay
20 RollAttack         21 Bomb               22 Shield            23 CrabWalk          24 ChangeTarget
25 SlingShot          26 Bow                27 FireArrow         28 IceArrow          29 LightArrow
30 DekuStick          31 DekuNut            32 Boomerang         33 Hookshot          34 Longshot
35 Hammer             36 Bombchu            37 DinFire           38 FaroreWind        39 NayruLove
40 SheikahWarp        41 MagicBean          42 Bottle            43 Save              44 HeadShortcut
45 BootShortcut       46 LockOnShield       47 Jump              48 Camera            49 GoronGauntlet
50 TimeTrail          51 ItemMenu           52 EquipmentMenu     53 ScrubBusinessSeed 54 AgonyStone
55 LockOnSideMove     56 Weapon_Shield_Hylian 57 Armor_Adult_Goron 58 Armor_Adult_Zora 59 FishingRod
60 Weapon_Shield_Mirror 61 SinkingLure      62 EquipmentMenuForHeadArmor 63 EquipmentMenuForBoot
64 OcarinaSongEstimate 65 ActivationAmiibo  66 AlarmCucco        67 ZeldaLetter
```

- The numbers are consistent with every flow above, for example 12 for the roof girl and 46 for the shield kid.
  `tools/evfl_params.py <romfs> ActionGuideType <flow>` lists a flow's values.

**Not text (images).** These are textures in `UI/Layout2Archive/Common.Product.100.Nin_Ounce_NVN2.bntx.zs`:
- the ocarina note buttons (`OcarinaButtonA_00`…`R_00`);
- the Talk ring's letters (`KeyTexFontA_00`…`Y_00`);
- the controls page's controller (`Controller_Pro*`, `ControllerGuide_Pro_0*`).

Triforce makes those per face too (section 5).

## 4. Overriding texts

### As a RomFS mod (tested)

```
python tools/mals_dump.py <game>/romfs <dump dir> USen            # every MSBT, label and text, to choose from
python tools/mals_edit.py --game <game> --lang USen --edits my-texts.tsv --mod 50-my-texts
```

- `my-texts.tsv` holds one text per line: `MSBT<tab>label<tab>new text`, written as the dump shows texts. `[ZL]` and so on
  become icon tags. See `tools/example-edits.tsv`.
- The tool writes `<game>/mods/50-my-texts/romfs/Mals/USen.Product.110.sarc.zs`. It checks that every edited text reads
  back as written and every other file is byte-identical.
- Run it once per language you want to change (`--lang EUen`, `JPja`, …); a language you leave out keeps its texts.

Things to know:
- **Start from Triforce's archive.** Triforce makes two edits of its own: the title's "Options / Triforce" entry and the
  microphone hint's wording for a PC. They are served from `<game>/prompts/mals/<lang>.product.110.sarc.zs`, but only
  when no mod has that file. `mals_edit.py --game` starts from that file, so your mod keeps them.
- **Size.**
  - The game drops a file bigger than its entry in `System/Resource/ResourceSizeTable` (each Mals archive has 336 bytes
    of slack).
  - Triforce's `host/mods.c` `hos_mods_table_size` gives every mod file its real size plus room. It reads that size from
    the zstd frame header, which `mals_edit.py` always writes.
  - Tested: archives larger by 1.2 KB and 155 KB loaded; the log says `mods: Mals/USen.Product.110.sarc gets … bytes to
    load in (the size table's 2373752 …)`.
  - On an emulator you would have to raise the size-table entry yourself.
- `triforce_log.txt` lists `mods: Mals/USen.Product.110.sarc.zs <- …` when the mod is used.

### Shipped inside a build (no game text in git)

Triforce already rewords two texts at build time from the player's own files: `nx2/prompt_assets.py` `title_messages` and
`PC_TEXTS`. Each wording is found by a fingerprint of the original and replaced, then served from `prompts/mals/`. You can
add your VR wordings the same way. Two limits:
- **Same length or shorter.** `title_messages` writes only archives no larger than the game's (`pc_texts` replaces
  inside the string's own room). For longer texts you have two options:
  - rebuild the MSBT and SARC (`msbt_build`, `txt2_build`, `sarc_replace`; `title_msbt` shows how) **and** give the file
    room, by adding a case to `hos_mods_table_size` for `prompts/mals/*` like the font's;
  - or raise the Mals entries in the size table that `prompts/rsizetable.zs` already serves (`size_table`).
- **A mod's archive wins.** A player's own Mals mod replaces your build edits for that language.

## 5. Replacing and slotting in button icons the way Triforce does

**How it works now.**
1. **The font.** Every icon in texts, panes and the HUD is a glyph of `Font2/Scalable/External.Nin_Ounce_NVN2.bfotf.zs`.
   That file is an OpenType/CFF font (83 icons, U+E040–E092) behind an 8-byte header and XORed per 32-bit word; see
   `unwrap`/`wrap` in `nx2/prompt_assets.py`.
2. **One font per face.** At Setup's build, `nx2/prompt_assets.py` writes `<game>/prompts/<face>/External.bfotf` for each
   face (switch, xbox, ps4, ps5, steamdeck, keyboard). `faces_font` and `face_font` build it as follows:
   - Copy each pad input's icon from the face's font: a Kenney Input Prompts glyph from `third_party/kenney_input`,
     scaled into the box of the game's glyph.
   - Put them at U+F700 + `HOS_PAD_*`.
   - Add every controller face's icons at U+F800 + 32×face + input, and one code per face, Switch button and pad input
     at U+F000 + (face×16 + button)×17 + input.
   - Give each Switch button's code point (E040–E047, E04B, E04C, E056, E057, E060–E063) a cmap format-4 segment of its
     own.
   - The D-pad pictures (E049, E064, E065) follow the face. The stick-direction icons (E050–E05F, E068) are not
     re-pointed: they keep the game's stick glyphs.
3. **Serving it.** `host/prompts.c`:
   - When the game opens the font, it serves the chosen face's file. `host/mods.c` `hos_mods_romfs` →
     `hos_prompts_romfs` does this, only when no mod has the font: **a mod that ships `External…bfotf.zs` turns Triforce's
     prompts off**.
   - Before serving, it points each Switch button's segment at the icon of the pad input **bound** to that button
     (`bind_font`, `cmap4_bind`, `bound_input`). So the icons show the player's own controls.
   - The live part: when the face or bindings change during play, it rewrites the cmap in the game's copy of the font
     (`live_font`). It also rewrites the button codes already laid out in text boxes (`text_rewrite`, hooked in
     `nx2/oot_patches.py`).
   - Room in the size table: `prompts/rsizetable.zs` and the font case in `hos_mods_table_size`.
4. **Images.**
   - The ocarina notes, the Talk ring letters and the controls-page controller are made per face (`face_layers`). Each is
     written over `prompts/Common.bntx` as block runs per Switch button × pad input (`<face>/textures.bin`, chosen by the
     bindings at load and live).
   - The Talk ring's and the ocarina hint's layouts are patched the same way (`ring.bin`, `hint.bin`).
   - Any image can be hand-drawn: run `python -I nx2/prompt_assets.py --romfs <romfs> --out <tmp> --dump <dir>` and put a
     PNG of the same name and size into `nx2/prompt_faces/<face>/` (`nx2/prompt_faces/README.md`).

**Slotting in your own icons. Pick one:**

1. **New glyphs on an existing face (no code).**
   - In `nx2/prompt_faces.py`, point the face's `font` at your own OpenType/TrueType font. Put it beside Kenney's in
     `third_party/kenney_input`, or change `KENNEY`.
   - Point its `prefix` and `icons` at your glyph names (`icons` maps pad inputs `south east west north back guide start
     lstick rstick lshoulder rshoulder up down left right ltrigger rtrigger` to glyph names).
   - Rebuild the prompts with Setup's Update, or
     `python -I nx2/prompt_assets.py --romfs <game>/romfs --out <game>/prompts`.
   - The notes, letters and Talk ring follow from the glyphs automatically.
   - The font needs vector outlines: they are drawn into the game's CFF font through fontTools pens. For PNG or SVG art,
     make the font first, for example with FontForge (import an SVG per glyph) or fontTools (`FontBuilder` + `SVGPath`).
     PNG art has to be traced to outlines first. The texture images (notes, letters, controller) can take PNGs
     directly.
2. **A new face** (for example `vr`), as the comment at the top of `nx2/prompt_faces.py` lists:
   - a `FACES` entry, placed before `"keyboard"`;
   - its `HOS_PROMPT_*` in `gpu/vk/vk_api.h`, before `HOS_PROMPT_KEYBOARD`;
   - its name in `host/prompts.c` `faces[]`;
   - `tx_prompts` and the `pad_name` rows in `gpu/vk/vk_menu.cpp`;
   - `tests/test_prompt_font_bind.py`, which checks the order.

   Limits:
   - There is room for exactly **one** more controller face. The per-binding codes use U+F000 + faces×16×17, and a sixth
     controller face reaches U+F660; a seventh would run into U+F700.
   - Inserting before the keyboard shifts the stored `button_prompts` value of keyboard users by one.

**VR specifics** (`gpu/vk/vk_xr.cpp` `Controls`):
- VR input goes straight onto the game's buttons through `vk_xr_pad`:
  - Touch A and B are A and B; X and Y act as A and B again;
  - a stick click is X (jump);
  - the left grip is ZL, the right grip ZR;
  - Menu tapped is Plus, held is Minus;
  - a sword swing is Y;
  - the gestures are the D-pad.
- This bypasses the pad bindings that Triforce's icons follow. For a VR face:
  - In `bound_input()` return the default input for every button (`switch_pad[]`) when the face is VR.
  - Give each pad input the glyph of the VR action on the Switch button it defaults to (`DEFAULT` in
    `prompt_assets.py`):

| Pad input | Default button | VR glyph |
|---|---|---|
| east | A | Touch A |
| south | B | Touch B |
| north | X | Stick click |
| west | Y | Swing |
| ltrigger, rtrigger | ZL, ZR | Left grip, right grip |
| start, back | Plus, Minus | Menu tap, Menu hold |
| up, down, left, right | D-pad | The four gestures |
| lstick, rstick | LS, RS | Stick presses |

  - Have `choose_face` pick the VR face while the headset runs (`vk_xr_head_active`), since Auto only knows SDL pads.
- Then every icon in texts, hints, guides and the ocarina notes shows the VR action, and the tutorial words can be
  reworded with section 4.

## 6. What was tested

All tests were windowed runs on a copy of the game (Triforce v0.8.3), with scripted input, on a PC. The real game folder
was not touched.

| Test | Result |
|---|---|
| Round trip: every text through `mals_dump` notation and `mals_edit` encode | Byte-identical, 21,138 texts in each of the 16 languages |
| Mod with the two title entries changed and a 1.5 KB text (archive +1,232 bytes, over the 336-byte slack) | Loaded: "New Game (text mod)" in the highlight colour. The log shows the mod file and its raised load size. |
| Raw code points U+E040/E046/E043 in the title text | Empty boxes |
| `{1.4:0f}{1.4:17}{1.4:27}{1.4:28}` in the title and `{1.4:0f}`/`{1.4:17}` in two area banners, keyboard face | Icons drawn as the bound keys: Z, Tab, Shift, Space |
| `{1.4:00}`…`{1.4:37}` across title entries, banners and the load dialog, Switch face | 00–29 read, giving the table in 3A (`icon-tag-values.jpg`). The dialog's buttons cut the rest off. |

Not tested: a dialogue box with your own text. Navi did not talk where the runs were, so no dialogue box opened in the
scripted run. The game's own dialogue uses the same `{1.4:NN}` tag (the shop lines), and Triforce's `text_rewrite` covers
text boxes.

## 7. Tools (`tools/`, Python 3 with `zstandard`; Triforce Setup's own `tools\python` has it)

| Tool | What it does |
|---|---|
| `mals_dump.py <romfs> <out> [Lang…]` | Every MSBT, label and text as TSV, plus the tags used |
| `mals_edit.py` | Writes a Mals mod from label → text lines (above) |
| `ctrlguide.py <romfs> <image.bin>` | The HUD control-hint table with names (`image.bin` is in the game folder) |
| `evfl_params.py <romfs> <param> <flow…>` | A parameter's values in event flows, e.g. `ActionGuideType` |
| `inspect_romfs.py`, `byml_dump.py` | Helpers: read any RomFS file unpacked, BYML as text, strings |
