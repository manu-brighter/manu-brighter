# Manual mode

The profile uses an ink, ice-blue and silver palette with original vector illustrations. The camera's iris, order routing, code review and scoreboard animations show distinct processes. Motion stops when the browser requests reduced motion.

- `manual-mode.html` is the editable browser preview. Open it directly to inspect the design and pause its animations.
- `manual-mode-art.json` contains the SVG illustration sources and their animation CSS.
- `fonts/` contains Manrope Regular and Bold, distributed under the SIL Open Font License in `fonts/OFL.txt`.
- `../scripts/render-manual-mode.py` lays out the GitHub image sections and outlines their typography.
- `../assets/manual-mode/` contains the generated desktop and mobile SVGs referenced by the profile README.

## Rebuild

Install Python 3 and the pinned fontTools dependency, then run from the repository root:

```shell
python -m pip install -r scripts/requirements-profile.txt
python scripts/render-manual-mode.py
```

The renderer runs locally without GitHub credentials or network access. Generated images contain no JavaScript, external images or external fonts. Their text is also available in accessible descriptions and README image alternatives. Project links live in the README because links inside an SVG image are not interactive on GitHub.

The HTML preview and production SVG renderer use separate layouts. After changing copy or spacing, update both and inspect desktop and mobile output. Update `manual-mode-art.json` when changing an illustration or its animation.

The profile intentionally uses its dark palette in both GitHub themes. The existing scheduled contribution graphics remain independent and are not embedded in this design.
