# Avatar licenses

These SVG avatars were generated with [DiceBear](https://www.dicebear.com/)
(MIT-licensed software) and are bundled locally so WeWatch does not call a
third-party API at runtime. Only CC0 1.0 styles are included
(see https://www.dicebear.com/licenses/):

| Files | Style | Original work | License |
| --- | --- | --- | --- |
| `notionists-*.svg` | Notionists | "Notionists" by Zoish | CC0 1.0 |
| `lorelei-*.svg` | Lorelei | "Lorelei" by Lisa Wischofsky | CC0 1.0 |
| `pixel-art-*.svg` | Pixel Art | DiceBear | CC0 1.0 |
| `thumbs-*.svg` | Thumbs | DiceBear | CC0 1.0 |

Each SVG also carries its license in embedded RDF metadata. Do not add
CC BY 4.0 styles (e.g. Adventurer, Micah, Personas) without adding visible
attribution to the UI.

To regenerate or extend a style:

```bash
curl -sf "https://api.dicebear.com/9.x/notionists/svg?seed=wewatch-notionists-13&backgroundColor=b6e3f4,c0aede,d1d4f9,ffd5dc,ffdfbf&radius=50" \
  -o static/avatars/notionists-13.svg
```
