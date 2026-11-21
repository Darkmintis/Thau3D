---
name: thau3d
description: Design or edit a building as a Thau3D spec and turn it into a furnished, walkable 3D model. Use when someone asks to design a house, office, apartment or other inhabited building, change a room's size or layout, add a storey, or preview a floor plan in 3D.
---

# Thau3D

You turn a described building into a `*.thau.json` spec, then build it into a GLB plus a manifest the Thau3D viewer can walk through.

**The spec is the deliverable.** The GLB is a build artifact. Never edit the GLB.

## When to use this

Use Thau3D when the user wants spatial, inhabited architecture: homes, apartments, offices, clinics, cafés, shops. Not for bridges, roads, parking layouts or anything where the point is traffic rather than rooms — the tool derives walls from touching rooms and has no vocabulary for those.

## The loop

1. **Read what exists.** If the repo has a spec, read it fully before editing. Never rewrite a spec from scratch when an edit will do.
2. **Ask only what you cannot infer.** Footprint, number of storeys, and the room program are required. Everything else has defaults.
3. **Write or edit the spec.**
4. **`thau3d validate <spec> --json`** — fix every error before continuing.
5. **`thau3d build <spec> -o viewer/public/models --json`** — check the warnings.
6. **`thau3d report <spec>`** — read the room schedule back to the user. Their sanity check is area, not pixels.
7. Tell the user to look at `http://localhost:5174` (or run `pnpm dev` in `viewer/`).

Treat `validate` output as your compiler. Errors are not suggestions.

## Writing a spec

Coordinates are **plan space**: `x` runs across the facade, `y` runs away from the street. `x: [0, 10]` means from the left wall to 10 units in. Units are declared once in `units` (`ft` or `m`).

Rooms on one storey must **tile the footprint without overlapping**. Every storey should cover the full footprint unless you want an unassigned area (validate warns).

```json
{
  "id": "living", "type": "living", "x": [10, 26], "y": [0, 12]
}
```

That is the whole room contract. No walls, no doors — the builder puts a door wherever two rooms share an edge, and a window on every habitable room that touches an exterior wall.

### Rules the validator enforces

- Every space sits inside `footprint`.
- No two spaces on a storey overlap.
- A stair must be contained by a space on its storey.
- Window head is above its sill.
- A storey above the ground floor is unreachable unless a stair starts on the storey below (warning).

### Exterior tools

- **Balconies** project past the footprint: `"balconies": [{ "storey": "first", "side": "front", "span": [16, 25], "depth": 4.5 }]`. They cut their own door in the wall behind them.
- **Roofs**: `terrace` (walkable, parapet), `flat`, `shed`, `gable` (with `pitch` and `ridge`).
- **Site**: `"site": { "surface": "grass" | "earth" | "gravel" | "paving" }` sets the ground material. Interior doors are hinged and open automatically in the viewer — you do not need to model them.
- **Stairs**: `"form": "u"` for a compact half-landing stair, `"form": "straight"` for a single long flight — the straight one needs about 4 m of run per storey.

### Room types you can use

`living` `lounge` `bedroom` `kitchen` `dining` `bath` `wc` `hall` `stair` `entry` `study` `office` `utility` `terrace` `balcony` `garage` `store`

The type selects the furniture recipe: bedrooms get a bed, nightstands and a wardrobe; kitchens get a counter, sink, hob, fridge and — if the room is big enough — an island; baths get a vanity, WC and shower; studies get a desk.

### Sensible dimensions (feet)

| Space | Typical |
|---|---|
| Bedroom | 10 × 12 minimum, 12 × 14 comfortable |
| Bath | 5 × 8 minimum |
| Kitchen | 10 × 12 |
| Stair | 8 × 10 footprint for a U-flight |
| Corridor | 3.5 wide |

Storey height 10 ft, clear height 9.25 ft are the defaults. A stair needs roughly 10 ft of run per 5 ft of rise at a walkable pitch.

## Editing an existing building

Change the numbers, not the structure, when possible:

- **"Make the kitchen bigger"** → move the boundary shared with a neighbour, and move the neighbour's other boundary back so the storey still tiles.
- **"Add a storey"** → duplicate the last storey, give it a new `id`, and add a stair on the storey below it.
- **"Add a bedroom"** → split an existing space in two and give both a `type`.

After any structural edit, run `validate` again: the most common failure is leaving a 0.4-unit gap or overlap at a boundary you moved.

## Outputs

| File | For |
|---|---|
| `<stem>.glb` | the model — Y-up, metres |
| `<stem>.manifest.json` | storeys, spaces, colliders, supports, stairs, luminaires, spawn |

Pass `--json` to `validate` / `build` when you are parsing the result yourself.

## Failure modes to avoid

- **Inventing structure.** If the user gives you a drawing or dimensions, those are the authority; do not silently "tidy" them.
- **Building a maze.** Doors are automatic and centred on shared edges. If a circulation route matters, shape the rooms so the shared edges land where you want the doors.
- **Forgetting the stair.** An upper storey with no stair below it validates with a warning and cannot be walked to.
- **Changing units mid-file.** Everything is in the declared `units`; do not mix feet and metres.
- **Claiming photoreal.** This produces readable, well-lit concept geometry — say that, do not oversell it.
