# Batkarai brand kit

**Name:** Batkarai (from Hindi *baat karna*, "to talk"). Written lowercase in the logo: `batkarai`.
**Tagline:** Talk to every lead in their own language.
**Contact:** hello@jmadhan.me

## Files

| File | Use |
|------|-----|
| `apps/web/src/app/icon.svg` | Browser favicon (also served at `/icon.svg`) |
| `apps/web/src/app/apple-icon.png` | iPhone home-screen icon, 180x180 |
| `apps/web/src/app/opengraph-image.png` | Link preview when the site is shared, 1200x630 |
| `apps/web/public/brand/logo-mark.svg` | Mark only, vector |
| `apps/web/public/brand/logo-mark-512.png` | Mark only, 512x512 PNG |
| `apps/web/public/brand/logo.svg` | Mark + wordmark, vector |

## Colours

| Name | Hex | Where |
|------|-----|-------|
| Ink navy | `#080A3A` | Text, buttons, wordmark |
| Deep indigo | `#2327A8` to `#06072F` | Logo tile gradient |
| Periwinkle | `#6B73F2` | Accent, links, first waveform bar |
| Coral | `#F59E8B` | Last waveform bar, glow |
| Dawn sky | `#B7C5F2` to `#FBE3D4` | Hero background |
| Page | `#F7F7FF` | Background |

Typeface: **Plus Jakarta Sans** (wordmark ExtraBold 800, headings SemiBold 600), JetBrains Mono for small labels.

## Prompt to generate a new logo with an AI image tool

Paste this into Midjourney, Ideogram, DALL-E, Firefly or similar:

> Minimal modern app icon logo for "Batkarai", an AI voice-calling platform for Indian languages. A rounded-square tile (squircle) with a deep indigo-to-midnight-navy diagonal gradient. Inside it, a clean white speech bubble with a small tail at the bottom-left, and inside the bubble five vertical rounded sound-wave bars of varying heights, coloured with a gradient from periwinkle blue (#6B73F2) at the left to soft coral (#F59E8B) at the right. Flat vector style, crisp geometry, generous padding, subtle soft shadow only, no text, no gradients other than the ones described, centred on a plain white background. Premium, friendly, trustworthy, suitable for a favicon at 16 pixels and for a 512 pixel app icon.

Wordmark prompt (optional):

> The word "batkarai" in lowercase, heavy geometric sans-serif (like Plus Jakarta Sans ExtraBold), tight letter spacing, deep navy (#080A3A), on a plain white background, flat vector, no effects.

Tips: ask for "vector, flat, svg style", generate 4 variations, and keep the winner's background transparent (export PNG with alpha) before placing it in `public/brand/`. Keep the 5-bar waveform inside a speech bubble: that is what makes the mark readable as "voice conversation" at small sizes.
