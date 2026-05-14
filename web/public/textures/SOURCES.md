# Texture Sources

License-clean provenance for every binary asset shipped under
`web/public/textures/`. Anything added here later must record source
URL, license, and how it's used inside the app — keeping this honest is
cheaper than relicensing later.

The design rationale for what gets a texture and what stays procedural
is documented in `web/src/styles/app.css` (see the body-backdrop,
parchment, and iron-chassis comment blocks). Short version: real
photographic textures from Transparent Textures are used for the three
material surfaces of the grimoire fiction —

1. **Ebony wood** — body backdrop. The deepest material layer.
2. **Dark leather** — `.iron-grained` chassis surfaces (front-ish).
3. **Aged paper** — `.parchment` cards (where text lives).

Plus one frontispiece engraving used as a hero plate on the empty save
shelf and campaign-end banner.

Earlier rounds of this experiment used procedurally-generated noise
PNGs for the substrate textures. They were obviously fake at retina and
forced multiple blend-mode compromises. The current set are all real
material photography, used at low opacity through carefully chosen
blend modes so they read as substrate without competing with content.

## `dark-wood.png` — body backdrop (ebony)

- **Role.** `body::before`, `overlay` blend at 35% opacity, 512px tile.
  Provides the ebony-wood grain that the rest of the grimoire sits on.
  Overlay on a near-black radial-gradient body darkens the darks and
  barely touches the candle-warm highlights, so the page reads as warm
  brown wood rather than as gray noise.
- **Source.** Transparent Textures (`dark-wood.png`),
  https://www.transparenttextures.com/patterns/dark-wood.png — a
  re-publication of Atle Mo's "Subtle Patterns" collection.
- **License.** Subtle Patterns / Transparent Textures content is
  distributed under a permissive MIT-style license that allows
  commercial use without attribution. Treated as license-clean for
  bundled redistribution inside this single-user desktop app.
- **Modifications.** None. Saved verbatim.

## `dark-leather.png` — chassis panels (.iron)

- **Role.** `.iron::after`, plain alpha at full opacity, 300px tile.
  Tooled near-black leather on every dark chassis (CharacterFolio,
  Inspector, SaveLibrary, chat container, dropdown menus). The PNG
  is a dark-gray/black texture with sparse alpha — its pixels stamp
  cleanly onto the iron gradient base without any CSS filter
  manipulation. Previous attempts to use `leather.png` with a
  `brightness(0.18)` filter crushed the texture to invisible (black
  pores on a near-black base = nothing renders).
- **Source.** Transparent Textures (`dark-leather.png`),
  https://www.transparenttextures.com/patterns/dark-leather.png —
  Subtle Patterns collection.
- **License.** Permissive MIT-style.
- **Modifications.** None.

## `concrete-wall.png` — cast-iron buttons

- **Role.** `button::before` / `.btn::before`, plain alpha at 60%
  (100% on hover), 200px tile. Sand-cast iron pitting on every
  clickable chip. The PNG is very dark (mean RGB ~15%) with sparse
  alpha — stamping it onto the dark button gradient adds the
  recognisable random pitting of cast iron without the linear scratches
  that would imply machined or polished metal.
- **Source.** Transparent Textures (`concrete-wall.png`),
  https://www.transparenttextures.com/patterns/concrete-wall.png —
  Subtle Patterns collection.
- **License.** Permissive MIT-style.
- **Modifications.** None.

## `black-felt.png` — top bar (draped cloth)

- **Role.** `.strip::after` override on the StatusStrip header,
  plain alpha at 85%, 200px tile. Reads as black cloth/felt stretched
  across the top of the workspace — different material from the
  leather-clad chassis below it. Paired with a vertical-fold
  `repeating-linear-gradient` on the `.strip` background to suggest
  draped folds along the X axis.
- **Source.** Transparent Textures (`black-felt.png`),
  https://www.transparenttextures.com/patterns/black-felt.png — Subtle
  Patterns collection.
- **License.** Permissive MIT-style.
- **Modifications.** None.

## `natural-paper.png` — parchment fibre

- **Role.** `.parchment::before`, `multiply` blend at 22% opacity,
  523x384 tile. The one texture layer on cream parchment, replacing
  the earlier stacked procedural stain + grain pair. Multiply darkens
  the cream paper naturally where the fibre is darker; the source
  tile's tight tonal range (std ~3%) keeps body text fully legible.
- **Source.** Transparent Textures (`natural-paper.png`),
  https://www.transparenttextures.com/patterns/natural-paper.png —
  Subtle Patterns collection.
- **License.** Same permissive MIT-style as `dark-wood.png`.
- **Modifications.** None.

## `knight-death-engraving.jpg` — frontispiece plate

- **Role.** Single hero engraving used by the `.frontispiece` utility:
  anchored on the empty save-shelf splash (`SaveLibrary` in `mode ===
  "empty"`) and on the campaign-end banner (`EndBanner`, strongest on
  the `death` variant). Rendered at 12–24% opacity with `screen` blend
  against the dark chassis so the figure reads as substrate, not
  illustration.
- **Source.** Albrecht Dürer, *Knight, Death and the Devil* (1513).
  Scan published by The Metropolitan Museum of Art and mirrored to
  Wikimedia Commons at
  https://commons.wikimedia.org/wiki/File:Knight,_Death,_and_the_Devil_MET_DP159047.jpg
  (full-resolution upload at
  https://upload.wikimedia.org/wikipedia/commons/2/2a/Knight%2C_Death%2C_and_the_Devil_MET_DP159047.jpg).
- **License.** The Met publishes its photography of out-of-copyright
  objects under CC0 1.0 / Public Domain through its Open Access
  program. Dürer's underlying 1513 engraving has been in the public
  domain since the early modern period. The Wikimedia mirror restates
  the same CC0 / public-domain status. No attribution required for
  use, but recorded here for honesty.
- **Modifications.** Resized to 800px wide, converted to grayscale,
  contrast levelled, JPEG re-encoded at quality 72 to keep the bundle
  small. Reproducible command:

  ```sh
  magick knight-death.jpg \
    -resize 800x \
    -colorspace Gray \
    -level 6%,94% \
    -quality 72 \
    knight-death-engraving.jpg
  ```

### 6. `linen.jpg`

- **Purpose.** Texture for the top status strip (`.strip`) and the
  reusable `.cloth` utility class. Reads as a dark draped fabric.
- **Source.** AI-generated source asset at `memory-bank/linen.png`
  (commissioned for this project, not from an external library).
- **Modifications.** Resized to 1600px wide and JPEG-encoded at q=82
  to keep bundle weight under 200 kB while preserving the natural
  drape and fold structure.
  ```sh
  magick memory-bank/linen.png -resize 1600x -quality 82 web/public/textures/linen.jpg
  ```

### 7. `cast-iron.jpg`

- **Purpose.** Surface texture for buttons / `.btn` chips. Reads as
  pitted matte iron with traces of rust.
- **Source.** AI-generated source asset at `memory-bank/cast_iron.png`
  (commissioned for this project).
- **Modifications.** Resized to 800x800 and JPEG-encoded at q=82.
  ```sh
  magick memory-bank/cast_iron.png -resize 800x800 -quality 82 web/public/textures/cast-iron.jpg
  ```

### 8. `gold.jpg`

- **Purpose.** Texture for the metallic scrollbar thumb in
  `web/src/lib/metalScroll.ts`. Reads as tarnished hammered brass /
  gilt with pitting.
- **Source.** AI-generated source asset at `memory-bank/gold.png`
  (commissioned for this project).
- **Modifications.** Resized to 1024px wide and JPEG-encoded at q=84.
  ```sh
  magick memory-bank/gold.png -resize 1024x -quality 84 web/public/textures/gold.jpg
  ```

## Tone fit

Why Dürer instead of an illuminated-manuscript scan: the campaign tone
is documented in `memory-bank/productContext.md` as gritty, oppressive,
late-medieval dark fantasy (Berserk / Fear & Hunger register). German
Renaissance grotesque engraving — Dürer, plague-doctor and Vesalius
anatomical plates, Goya's *Disasters of War* — matches that register.
Lions-and-vines ecclesiastical illumination does not, and would
mismatch the in-app fiction (Mahabre / Gro-goroth / God of the Depths
lore set in the directives).

Future additions should keep that constraint: if a candidate plate
reads as celebratory medieval optimism, skip it.

## Why three real textures, not procedural

Earlier iterations of this CSS used procedurally-generated PNGs
(`iron-grain.png`, `paper-stains.png`, plus several short-lived
attempts at `ebony-grain` and `leather-grain`). Two reasons they were
all retired:

1. **Retina visibility vs. authenticity tradeoff.** Procedural Gaussian
   noise looks "right" at 1x DPR but collapses to imperceptible
   cross-hatch at 2x+, while real material photography retains
   recognisable structure (knots, pore clusters, fibre direction) at
   every pixel density.
2. **Blend-mode debugging cycles.** Procedural mid-gray noise on a
   near-black backdrop turns gray under almost every blend mode that
   makes it register at all. Real wood / leather are inherently
   dark-warm, so the same blends shift the page toward brown — which
   is the visible payoff the dark backdrop needed.

Transparent Textures' permissive license and CC0-equivalent treatment
makes this a free win — the bundle is smaller (one PNG per surface
instead of two layered procedurals) and the result is recognisable as
the material it's supposed to be.
