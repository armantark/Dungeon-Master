# Texture Sources

License-clean provenance for every binary asset shipped under
`web/public/textures/`. Anything added here later must record source
URL, license, and how it's used inside the app — keeping this honest is
cheaper than relicensing later.

The design rationale for what gets a texture and what stays procedural
is documented in `web/src/styles/app.css` (see the substrate-grain,
iron-chassis, and `.frontispiece` comment blocks). Short version: photo
textures are reserved for *substrate degradation* (paper tooth, metal
grain) and for one or two *frontispiece moments* (campaign end, empty
shelf). They are not used as UI chrome — buttons, tags, receipts, and
pigment math stay derived from the `:root` palette.

## `paper-grain.png` — body substrate

- **Role.** Replaces the previous `feTurbulence` SVG overlay on
  `body::before`. Rendered at 10% opacity under `mix-blend-mode:
  overlay` so it reads as paper fibre at glancing angle without
  competing with type or pixel chips.
- **Source.** Transparent Textures (`paper-2.png`),
  https://www.transparenttextures.com/patterns/paper-2.png — a
  re-publication of Atle Mo's "Subtle Patterns" collection.
- **License.** Subtle Patterns / Transparent Textures content is
  distributed under a permissive MIT-style license that allows
  commercial use without attribution. The pattern itself is a small
  tileable PNG; we treat it as license-clean for bundled
  redistribution inside this single-user desktop app.
- **Modifications.** None. Saved verbatim as `paper-grain.png`.

## `paper-stains.png` — coarse low-frequency stain plate

- **Role.** The *visible-at-retina* substrate layer for both the body
  backdrop (`body::after`, screen blend) and parchment cards
  (`.parchment::after`, multiply blend). The fine paper-grain.png tile
  collapses to a sub-pixel cross-hatch at 2x DPR; this plate is at
  1024px so its features land at 50-200 logical pixels and stay
  perceptible regardless of pixel density.
- **Source.** Locally generated with ImageMagick. Reproducible command:

  ```sh
  magick -size 1024x1024 xc:gray50 \
    +noise gaussian \
    -virtual-pixel tile \
    -blur 0x22 \
    -level 22%,78% \
    -colorspace Gray \
    -depth 8 \
    -define png:compression-level=9 \
    paper-stains.png
  ```

  Gaussian noise plus a heavy 22-pixel blur produces low-frequency
  blotchy patches; the level remap compresses contrast so the result
  is mid-gray noise rather than full black-and-white. Tileable
  (`-virtual-pixel tile`).

- **License.** Procedurally generated; treated as CC0-equivalent.

## `iron-grain.png` — iron chassis substrate

- **Role.** Procedurally generated tileable PNG used by the
  `.iron::after` overlay (8% opacity, `mix-blend-mode: overlay`) so
  dark chassis surfaces — `SaveLibrary`, future iron panels — read as
  cast-iron rather than a flat tinted gradient.
- **Source.** Locally generated with ImageMagick on the maintainer's
  machine. Reproducible command:

  ```sh
  magick -size 192x192 xc:gray50 \
    +noise gaussian \
    -virtual-pixel tile \
    -motion-blur 0x2+45 \
    -blur 0x0.6 \
    -level 35%,65% \
    -colorspace Gray \
    -depth 8 \
    -define png:compression-level=9 \
    iron-grain.png
  ```

- **License.** Generated noise has no underlying authored work, so we
  treat the resulting PNG as CC0-equivalent for redistribution.

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
