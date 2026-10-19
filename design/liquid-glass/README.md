# Liquid Glass UI kit

A standalone reproduction of the KEEL Liquid Glass material: open `index.html` in a browser.
`liquid-glass.css` holds every component, driven by the custom properties in `:root`.

| Class | What it is |
|---|---|
| `.lg-stage` | Silver studio backdrop, lit from the top-left |
| `.lg-plate` | Thick polished glass plate: 1.5px `rgba(255,255,255,.7)` edge, `blur(35px) saturate(180%)`, edge refraction, sheen and a long ambient shadow |
| `.lg-gel` / `.lg-gel--mint` / `.lg-gel--sm` | Luminous liquid-gel button: radial colour core, top-left inner glow, gloss cap, glow shadow in the button's own colour |
| `.lg-pill` + `.lg-search`, `.lg-check`, `.lg-iris`, `.lg-toggle` | Frosted glass pills sitting on the plate |
| `.lg-card`, `.lg-field` | Small frosted cards and inputs |
| `.lg-avatar` | Iridescent luminous avatar ring |
| `.lg-folder` / `.lg-folder--clear` | Pastel liquid trapped in glass, casting coloured light onto the plate |

The product uses the same rules in `frontend/src/styles/apex-glass.css`. The light theme is the default; the dark theme swaps only the `--lg-*` tokens.
`backdrop-filter` needs a current Chromium, Safari or Firefox; older browsers show the same layout without the blur.
