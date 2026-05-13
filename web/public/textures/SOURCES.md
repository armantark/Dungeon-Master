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

## `leather.png` — `.iron` chassis surfaces

- **Role.** `.iron::after`, plain-alpha at full opacity, 300px tile.
  The "front-ish" dark surface — leather-clad iron panels used on
  every `.iron` chassis (CharacterFolio, Inspector, SaveLibrary, hero
  panels, dropdown menus). The PNG is alpha-stamped on top of the iron
  gradient: its mid-tan brown pixels with sparse alpha give the
  surface its leather pores against the dark base.
- **Source.** Transparent Textures (`leather.png`),
  https://www.transparenttextures.com/patterns/leather.png — Subtle
  Patterns collection.
- **License.** Same permissive MIT-style as `dark-wood.png`.
- **Modifications.** None.

## `brushed-metal.png` — buttons and dropdowns

- **Role.** `button::before` / `.btn::before` pseudo, plain-alpha at
  55% (85% on hover), 200px tile. Stamps faint brushed-aluminium
  scratch highlights onto the dark button gradient so clickable chrome
  reads as a separate material from static iron panels. On hover the
  pseudo brightens and a `sepia/saturate/hue-rotate` filter chain
  warms the brushed marks toward gold — the affordance is the metal
  "catching light" rather than a flat color swap.
- **Source.** Transparent Textures (`brushed-alum-dark.png`),
  https://www.transparenttextures.com/patterns/brushed-alum-dark.png —
  Subtle Patterns collection.
- **License.** Same permissive MIT-style as `dark-wood.png`.
- **Modifications.** Renamed from `brushed-alum-dark.png` to
  `brushed-metal.png` for clarity; otherwise verbatim.

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
