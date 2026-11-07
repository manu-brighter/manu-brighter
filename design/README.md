# Manual mode

The profile combines a dark background with lime, violet and chrome. A mechanically consistent camera iris, an Audi S5 drawn as a clean side elevation, public project activity and a branching life graph connect the developer and photography sides. Motion follows the aperture, order routes with a brief arrival highlight, the parked car's contour and the life branches. It stops when the browser requests reduced motion.

Skills are grouped by domain immediately after the introduction, with AI-assisted project technologies explicitly identified. All six projects follow in one overview: each row links to its repository through the project artwork and gives its purpose, technology and status. The club's animated case study is expandable inside that overview. The completed Shot-Counter app links to its downloadable releases. Completed and concluded work remains visible alongside active projects; the activity graph separately samples four public repositories.

The introduction and link labels use the same outlined Manrope typography and content insets as the illustrations. The two navigation rows each contain three independently linked images, with desktop and mobile variants. Download and photography links use full-width image rows. Their links remain ordinary README anchors, so they also work on GitHub; no custom README CSS or interactive SVG links are required.

- `manual-mode.html` previews the actual generated SVGs. Open it directly to inspect the current desktop or mobile design.
- `art/` contains the editable camera and S5 vectors and their animation CSS. The S5 follows the supplied side-profile line drawing, mirrored to face right. Its lowered body, polished five-split-Y wheels, slim tyres and boot-lip spoiler are drawn as editable vector paths. The moving polish is masked to the metal; the wheels remain stationary. The DRL brow, outer hook and separated inner return follow the supplied B8.5 headlight photograph, with a restrained animated glow.
- `art/fly-experiment.svg` is a schematic stimulus-response loop beside the Connectome project. It illustrates a cue, signal propagation and orientation, not a real replay or learned behaviour. `art/mining-turtle.svg` adds a compact voxel robot beside the 2014 milestone. It advances two short steps, mines one block and returns before a code-brace trail appears. Both use 16-second CSS cycles with rest phases and static reduced-motion states. The timeline also uses `art/efz-document.svg`, `art/first-photo.svg` and `art/fly-classroom.svg` beside their respective milestones. Their short actions are staggered within 18-second cycles. The classroom is a playful metaphor, not a simulation result. All four timeline illustrations occupy a reserved right-hand column; mobile graph lanes are closer together to retain readable text.
- `data/activity.json` is the checked-in public activity snapshot used for local previews and reproducible builds.
- `fonts/` contains Manrope Regular and Bold, distributed under the SIL Open Font License in `fonts/OFL.txt`.
- `../scripts/render-manual-mode.py` lays out the GitHub image sections and outlines their typography.
- `../assets/manual-mode/` contains the generated desktop and mobile SVGs referenced by the profile README.

## Rebuild

Install Python 3 and the pinned fontTools dependency, then run from the repository root:

```shell
python -m pip install -r scripts/requirements-profile.txt
python scripts/render-manual-mode.py
```

The renderer runs locally without GitHub credentials or network access, using the checked-in activity snapshot. Generated images contain no JavaScript, external images or external fonts. Their text is also available in accessible descriptions and README image alternatives. Project links live in the README because links inside an SVG image are not interactive on GitHub.

Edit copy and layouts in the renderer; edit illustrations in `art/`. Regenerate the assets, then inspect both desktop and mobile widths in the preview. The preview uses the same SVGs as GitHub, so it does not maintain a second layout implementation. The supplied drawing and wheel photographs are visual references and are not embedded or committed.

## Public activity

`scripts/fetch-profile-activity.mjs` reads four fixed public repositories via the GitHub REST API: Jogge di Balla, Fly Connectome Sim, Claude Code Kit and the portfolio. It counts commits authored by `manu-brighter` on each repository's actual default branch, including merges. Each head SHA is pinned before pagination. Days use the commit's **committer timestamp**; twelve calendar months are shown on a shared scale. The view ends on the latest completed UTC day, so the latest month can be partial. For example, `--until 2026-11-06` covers December 2025 through 5 November 2026; `--until 2026-11-01` covers all of November 2025 through October 2026. Schema version 2 records the month labels and variable day count explicitly. This is project activity, not GitHub's contribution calendar or all professional work.

```shell
node scripts/fetch-profile-activity.mjs --output design/data/activity.json
node --test scripts/test-profile-activity.mjs
python scripts/render-manual-mode.py --only activity
```

The fetcher uses `GITHUB_TOKEN`, or an authenticated `gh` session locally. `--until YYYY-MM-DD` selects an exclusive UTC boundary for reproducible periods. A failed, private or incomplete response aborts without replacing the previous snapshot. No tokens, emails or commit messages enter the published JSON.

`.github/workflows/profile-activity.yml` runs a six-hour refresh at minute 17. It publishes only `activity.svg`, `activity-mobile.svg` and `activity.json` to `chore/profile-data`; the README references these independent images. The preview deliberately uses the local snapshot. GitHub may cache published images, and scheduled jobs can be delayed. The visible timestamp identifies the snapshot actually being shown.

GitHub runs the schedule from the default branch, `main`. A manual run of **Refresh public project activity** can refresh the published snapshot between scheduled runs. No workflow step pushes to `main`, `master` or `develop`.

The profile intentionally uses its dark palette in both GitHub themes. The older contribution graphics workflow remains independent and is not embedded in this design.
