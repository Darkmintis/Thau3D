# The Thau3D spec

Version `0.1`. A spec is a JSON object that describes a building as a stack of storeys, each tiled by spaces. Everything else — walls, doors, windows, slabs, stairs, furniture, lights — is derived.

The machine-readable definition is [`schema/thau.schema.json`](../schema/thau.schema.json).

## Coordinate system

Plan space, like a drawing on a desk:

```
        y = depth  (away from the street)
        ^
        |
   back |__________________________
        |                          |
        |   rooms tile this area   |
        |                          |
  street|__________________________|  -> x = width
```

- `x` runs across the facade, starting at the left party wall (`x: 0`).
- `y` runs away from the street, starting at the front elevation (`y: 0`).
- Heights come from `defaults`, not from the spec's room rectangles.

The exporter converts to glTF's Y-up convention once, in [`thau3d/geometry.py`](../thau3d/geometry.py). Spec authors never think about it.

## Units

Declare `"units": "ft"` or `"units": "m"` once. **Every** length in the file uses it, including `defaults`, `site` and window sills. Internally everything becomes metres.

## Shape of the file

```jsonc
{
  "version": "0.1",
  "name": "Kirtipur Terrace House",
  "units": "ft",

  "footprint":  { "width": 26, "depth": 38 },
  "defaults":   { "storeyHeight": 10, "clearHeight": 9.25, "exteriorWall": 0.75 },
  "site":       { "width": 40, "depth": 56, "path": { "x": [3.5, 6.5], "from": -7, "to": 0 } },
  "entrance":   { "space": "entry", "side": "front", "width": 3.6 },
  "materials":  { "wall": "#F1ECE2" },

  "storeys": [ { "id": "ground", "spaces": [ /* … */ ] } ],
  "stairs":  [ { "id": "to_first", "storey": "ground", "x": [1, 9], "y": [26, 36] } ],
  "windows": [ { "space": "living", "side": "front", "width": 9, "sill": 2.5, "head": 7.6 } ],
  "doors":   [ { "between": ["entry", "living"], "width": 3.2 } ],
  "roof":    { "type": "terrace", "parapet": 3.2 }
}
```

## Storeys and spaces

Each storey has an `id` (`ground`, `first`, `second`, …) and an array of spaces. Spaces are **rectangles** in plan: `"x": [x0, x1], "y": [y0, y1]`.

Two rules make everything else work:

1. Spaces on a storey must not overlap.
2. Spaces should tile the footprint. Gaps become unassigned floor, and `validate` warns about them.

Space `id`s only need to be unique within a storey, so `stair` can appear on all three. A window or door that refers to a repeated id can disambiguate with `"storey": "first"`.

### Space types

| Type | Gets |
|---|---|
| `living`, `lounge` | sofa, cushions, coffee table, media console, TV, rug |
| `bedroom` | bed, bedside tables and lamps, wardrobe, rug |
| `kitchen` | base and wall cabinets, worktop, sink, hob, fridge, island and stools when there is room |
| `dining` | table and up to four chairs |
| `bath`, `wc` | vanity, basin, mirror, WC, shower tray and screen |
| `entry`, `hall` | console, mirror, vase |
| `study`, `office` | desk, chair, shelf |
| `terrace`, `balcony` | bench and planters |
| `utility` | washer and shelf |
| `garage` | paved floor |
| `stair`, `store` | nothing |

## How walls are derived

**Exterior walls** run the full perimeter of the footprint, `defaults.exteriorWall` thick, centred on the boundary. Each elevation is split into solid segments around its openings.

**Interior walls** appear wherever two spaces share an edge. The shared span is measured, and a door is centred in it, clamped so it never touches the corners. No shared edge, no wall — this is why the shape of your rectangles *is* the plan.

**Doors** are automatic. Override one with a `doors` entry naming a pair of spaces; `offset` shifts it along the shared edge.

**Windows** come from two places:

1. Explicit `windows` entries — full control over side, width, sill and head.
2. Automatically: every habitable room (`living`, `bedroom`, `kitchen`, `dining`, `study`, `office`, `lounge`) that touches an exterior wall gets one, sized to about 60% of that wall and capped at 2.6 m.

Each window becomes a pane plus a slim dark frame. The entrance becomes a framed opening with no leaf, so you can walk straight in.

## Stairs

```json
{ "id": "to_first", "storey": "ground", "x": [1, 9], "y": [26, 36], "width": 4, "form": "u" }
```

- `storey` is where the flight **starts**. It climbs to the next storey up.
- The rectangle must sit inside a space on that storey.
- `form: "u"` builds two flights around a half-landing; the return flight lands beside the first.
- Riser height is derived: `storeyHeight / 2 / ceil((storeyHeight / 2) / 0.19)`, so it never exceeds 19 cm.
- The storey above gets a stairwell hole cut in its slab automatically, and the roof gets one if a stair starts on the top storey.

## Roof

`{"type": "terrace", "parapet": 3.2}` builds a slab over the top storey plus a parapet wall around the perimeter. The terrace is a walkable support, so a stair to the roof is usable.

## Materials

Any material key from [`thau3d/materials.py`](../thau3d/materials.py) can be retinted by colour:

```json
"materials": { "wall": "#EDE6D8", "floor": "#C9A87C", "stone": "#3B4145" }
```

Overrides change colour only; roughness and metalness stay with the palette. This is the cheap way to answer "make it warmer" without touching geometry.

## What the build produces

| File | Contents |
|---|---|
| `<stem>.glb` | the model: metres, Y up, one node per primitive, `extras.storey` on every node |
| `<stem>.manifest.json` | the walkable semantics |

The manifest is what makes the model a *place* rather than a mesh:

```jsonc
{
  "storeys":  [ { "id": "ground", "base": 0, "top": 3.048, "height": 3.048 } ],
  "spaces":   [ { "id": "living", "rect": [0,0,4.9,3.7], "area": 17.8, "center": [2.4,0,-1.8] } ],
  "stairs":   [ { "id": "to_first", "steps": [ { "rect": [...], "top": 0.169 } ], "top": 3.048 } ],
  "colliders":[ { "min": [x,y,z], "max": [x,y,z], "tag": "wall" | "furniture" | "glass" } ],
  "supports": [ { "min": [...], "max": [...], "tag": "floor" | "stair" | "ground" | "roof" } ],
  "luminaires":[ { "position": [x,y,z], "intensity": 18.7, "distance": 8.6 } ],
  "spawn":    { "position": [x,y,z], "yaw": -0.93 }
}
```

A viewer needs nothing else: colliders to block movement, supports to stand on, stairs to climb.

## Limits in 0.1

- Rectilinear plans only — spaces are axis-aligned rectangles.
- One stair form (`u`), no spiral or external stairs.
- Flat or terrace roofs; no pitched roofs, no dormers.
- Balconies are spaces, not projecting volumes.
- No doors with leaves, no cabinetry details, no textures.
- The furniture vocabulary is deliberately small and reads as clean concept geometry, not photoreal.
