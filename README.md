# Thau3D

**Describe a place. Get a building you can walk through.**

`thau` is Nepali for *place*. Thau3D turns a short, declarative spec into a furnished, walkable 3D building — a GLB plus a manifest the browser viewer uses for collision, stairs, rooms and lighting.

It is built for **AI agents as the editor**: you describe the building in `*.thau.json`, any coding agent (Cursor, Claude Code, Codex, your own harness) edits that file, and the CLI tells you — in text — whether the result is a real, coherent building.

```bash
python -m thau3d validate examples/housewalk/house.thau.json
python -m thau3d build    examples/housewalk/house.thau.json -o viewer/public/models
cd viewer && pnpm install && pnpm dev     # walk it at http://localhost:5174
```

No GPU, no Blender, no native dependencies. The builder is pure Python standard library and produces a 600 KB GLB in about a second.

---

## Why a spec and not a mesh

Text-to-3D gives you a pretty mesh you cannot measure, cannot trust and cannot walk. Thau3D inverts that: the **spec is the source of truth**, geometry is derived deterministically, and the walkable semantics (colliders, floors, stairs, room names) come from the same derivation, not from guessing node names.

That means:

- **Every change is a diff.** `git diff house.thau.json` is the whole story of what the agent did.
- **Impossible geometry fails loudly.** Overlapping rooms, stairs outside their space, windows on walls that do not exist — all reported before a single triangle is built.
- **The same file renders forever.** Deterministic output, no sampling, no seed drift.

## The spec is room-first

You do not place walls. You describe spaces, and the builder works out the walls between them.

```json
{
  "version": "0.1",
  "name": "Kirtipur Terrace House",
  "units": "ft",
  "footprint": { "width": 26, "depth": 38 },
  "storeys": [
    {
      "id": "ground",
      "spaces": [
        { "id": "entry",   "type": "entry",   "x": [0, 10],  "y": [0, 12] },
        { "id": "living",  "type": "living",  "x": [10, 26], "y": [0, 12] },
        { "id": "dining",  "type": "dining",  "x": [0, 10],  "y": [12, 24] },
        { "id": "kitchen", "type": "kitchen", "x": [10, 26], "y": [12, 24] },
        { "id": "stair",   "type": "stair",   "x": [0, 10],  "y": [24, 38] },
        { "id": "study",   "type": "study",   "x": [10, 26], "y": [24, 38] }
      ]
    }
  ],
  "stairs": [
    { "id": "to_first", "storey": "ground", "x": [1, 9], "y": [26, 36], "width": 4 }
  ],
  "roof": { "parapet": 3.2 }
}
```

From that, the builder derives: exterior walls with window and door openings, party walls with doors wherever two rooms share an edge, floor and roof slabs (with stairwell holes), a furnished interior per room type, ceiling lights, and a walkable stair that actually connects the storeys.

See [`docs/SPEC.md`](docs/SPEC.md) for every field, and [`schema/thau.schema.json`](schema/thau.schema.json) for editor autocomplete.

## CLI

| Command | What it does |
|---|---|
| `thau3d validate <spec>` | Parse, normalise and check a spec. Errors exit non-zero; warnings explain what will look off. |
| `thau3d build <spec> -o <dir>` | Write `<stem>.glb` + `<stem>.manifest.json`. |
| `thau3d report <spec>` | Room schedule: dimensions, net area and totals per storey. |

Every command accepts `--json` for machine-readable output. That is the interface an agent should use.

```
$ thau3d build examples/housewalk/house.thau.json -o viewer/public/models
built house.glb
  418 nodes · 5,796 triangles · 615 KB · 27 materials
  ground: 6 spaces · 91.8 m² net
  first: 6 spaces · 91.8 m² net
  second: 6 spaces · 91.8 m² net
```

## The viewer

`viewer/` is a Vite + Three.js app. It reads the GLB and the manifest and gives you:

- **Exterior orbit** with day/night lighting and image-based reflections
- **Projecting balconies** with glazed balustrades, pitched roofs and straight or U stairs, all driven by the spec
- **Doors that open** as you walk towards them, and grounds chosen by material — earth, grass, gravel, paving — fading into a horizon
- **Room list** built from the manifest — click a room to fly to it
- **Storey isolation** to inspect one floor at a time
- **First-person walk** with pointer lock or touch, AABB collision, gravity and real stair climbing
- **Interior lights** driven by the manifest's luminaires

Because collision and stairs come from the manifest rather than from mesh names, changing the spec cannot silently break movement.

## What is in here

```
thau3d/          the builder: spec -> glTF, zero dependencies
  spec.py        parsing, normalisation, validation
  build.py       slabs, walls, openings, stairs, roof, manifest
  furniture.py   procedural room recipes
  geometry.py    plan-space primitives -> glTF space
  glb.py         minimal GLB writer
  cli.py         validate / build / report
schema/          JSON Schema for the spec
examples/        worked buildings (start with housewalk)
viewer/          Vite + Three.js walkthrough
skill/           SKILL.md — how an agent should use this repo
docs/SPEC.md     the spec reference
```

## Coordinates and units

Specs are written in **plan space**: `x` runs across the facade, `y` runs away from the street, `z` is up. Units are declared once (`ft` or `m`) and converted internally to metres. The exporter maps plan space to glTF's Y-up convention, so the GLB drops into any engine without a rotation hack.

## Status

`0.2` — the spec, builder, manifest, viewer and verification layer work end to end: projecting balconies, pitched roofs, two stair forms, glazed window and balustrade systems. Known gaps: rectilinear plans only, no dormers, and a deliberately small furniture vocabulary. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## License

Code is Apache-2.0. Generated models are yours. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
