# Roadmap

## 0.1 — shipped

- [x] Room-first spec + JSON Schema
- [x] Validator with actionable, human-readable errors
- [x] Dependency-free GLB writer (plan space -> glTF Y-up)
- [x] Walls derived from adjacency, doors auto-placed, windows auto or explicit
- [x] Slabs with stairwell holes, U stairs, terrace roof with parapet
- [x] Procedural furniture per room type, ceiling finishes, ceiling lights
- [x] Manifest: storeys, spaces, colliders, supports, stairs, luminaires, spawn
- [x] Vite + Three.js viewer: orbit, storey isolation, room focus, first-person walk, day/night, touch
- [x] `SKILL.md` for agents, 25 tests, determinism test

## 0.2 — make it feel like a real building

- Balcony volumes that project past the facade (the single biggest visual upgrade)
- Pitched and shed roofs, plus roof access hatches
- Straight-run and dog-leg stairs alongside the U
- Door leaves, sliding doors for balconies and wardrobes
- Window reveals, mullions, and a sill/threshold profile family
- Material families: stone bases, rendered upper floors, timber cladding

## 0.3 — make it useful for real dimensions

- Room-by-room area report as a first-class CLI output (`report --verify` against target areas)
- Storey-area totals with circulation allowance
- Clearance check: door widths, corridor widths, stair headroom, turning circles
- Import dimensions from a plan: `thau3d trace` to help place rectangles over a raster
- Assumption tracking: mark every dimension as `drawing` or `assumed`, surface it in the report

## 0.4 — make it sharable

- `?model=` already works; add `?spec=` so a spec URL rebuilds in the browser
- Export a shareable still and a 10-second orbit clip
- GitHub Pages demo of `examples/housewalk`
- Embed mode for client presentations

## Later

- Non-rectilinear spaces (L-shaped rooms, angled party walls)
- Asset library: real GLB furniture swapped in by `id`, with `WalkBlock_` colliders from the asset manifest
- Multiple buildings per scene, site layout, orientation and solar study
- Blender bridge: export a `.blend` for hero renders while the spec stays the source of truth
- Diffable builds: `thau3d build --diff previous.manifest.json` to explain what an edit changed

## Explicitly not planned

- Photorealism. The output is readable concept geometry; paths and glass and lighting matter more than textures.
- Parking, roads and traffic simulation. Different tool, different questions.
- A GUI editor. The agent and the spec file are the editor — that constraint is what keeps the geometry trustworthy.
