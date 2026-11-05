# Manual mode

The profile combines a dark background with lime, violet and chrome. Its original camera, lowered black Audi S5 B8.5 and polished KC Forged wheels share this lighting palette. Motion shows the camera aperture, order routing, parked-car reflections and flow through a Git-style life graph. It stops when the browser requests reduced motion.

- `manual-mode.html` previews the actual generated SVGs. Open it directly to inspect the current desktop or mobile design.
- `art/` contains the editable camera, S5 and wheel illustrations and their animation CSS.
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

Edit copy and layouts in the renderer; edit illustrations in `art/`. Regenerate the assets, then inspect both desktop and mobile widths in the preview. The preview uses the same SVGs as GitHub, so it does not maintain a second layout implementation. The supplied photographs are references for the car and wheel drawings and are not embedded in the profile.

The profile intentionally uses its dark palette in both GitHub themes. The existing scheduled contribution graphics remain independent and are not embedded in this design.
