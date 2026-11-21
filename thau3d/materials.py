"""The Thau3D material palette.

Every material has a stable key. A spec can retint any of them through
``"materials": {"wall": "#e8e2d6"}`` without touching geometry, which is what
makes "make the walls warmer" a one-line change for an agent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialDef:
    color: str
    metallic: float = 0.0
    roughness: float = 0.85
    opacity: float = 1.0
    emissive: str | None = None
    emissive_strength: float = 1.0
    double_sided: bool = True

    def with_color(self, color: str) -> "MaterialDef":
        return MaterialDef(
            color=color,
            metallic=self.metallic,
            roughness=self.roughness,
            opacity=self.opacity,
            emissive=self.emissive,
            emissive_strength=self.emissive_strength,
            double_sided=self.double_sided,
        )


PALETTE: dict[str, MaterialDef] = {
    # shell
    "wall": MaterialDef("#F3EFE6", roughness=0.9),
    "wall_inner": MaterialDef("#EFEBE2", roughness=0.92),
    "slab": MaterialDef("#C9C6BD", roughness=0.88),
    "floor": MaterialDef("#D8D3C8", roughness=0.82),
    "plinth": MaterialDef("#B9B5AC", roughness=0.9),
    "roof": MaterialDef("#C7C3BA", roughness=0.9),
    "stone": MaterialDef("#454B50", roughness=0.95),
    "stone_light": MaterialDef("#8A8781", roughness=0.93),
    "concrete": MaterialDef("#BFBDB6", roughness=0.9),
    # joinery and metal
    "frame": MaterialDef("#23292F", metallic=0.35, roughness=0.45),
    "metal": MaterialDef("#2B3238", metallic=0.75, roughness=0.32),
    "steel": MaterialDef("#B4B9BA", metallic=0.8, roughness=0.28),
    "brass": MaterialDef("#B08D57", metallic=0.85, roughness=0.3),
    # glazing
    "glass": MaterialDef("#B4CFD6", metallic=0.06, roughness=0.06, opacity=0.14),
    "glass_clear": MaterialDef("#C7D9DC", metallic=0.05, roughness=0.05, opacity=0.18),
    # timber
    "oak": MaterialDef("#B78B5E", roughness=0.7),
    "oak_light": MaterialDef("#CBA579", roughness=0.72),
    "walnut": MaterialDef("#6C4A32", roughness=0.68),
    "ply": MaterialDef("#D3B790", roughness=0.8),
    # textiles
    "linen": MaterialDef("#E6E0D4", roughness=0.98),
    "linen_dark": MaterialDef("#C6BBA8", roughness=0.98),
    "fabric_ivory": MaterialDef("#DCD5C6", roughness=0.98),
    "fabric_sage": MaterialDef("#8C9A85", roughness=0.98),
    "fabric_clay": MaterialDef("#B98C74", roughness=0.98),
    "rug": MaterialDef("#A99C88", roughness=0.99),
    "bedding": MaterialDef("#DED7C9", roughness=0.98),
    "throw": MaterialDef("#7E8C7A", roughness=0.98),
    # sanitary and kitchen
    "ceramic": MaterialDef("#F0F0EA", roughness=0.25),
    "quartz": MaterialDef("#DCD9D0", roughness=0.3),
    "mirror": MaterialDef("#DDE6E8", metallic=1.0, roughness=0.05),
    "appliance": MaterialDef("#2A2F33", metallic=0.4, roughness=0.25),
    # light and life
    "led": MaterialDef("#FFD79A", roughness=0.3, emissive="#FFB35C", emissive_strength=1.0),
    "led_off": MaterialDef("#6B573C", roughness=0.5),
    "foliage": MaterialDef("#4C6B4B", roughness=0.9),
    "terracotta": MaterialDef("#B08A6A", roughness=0.85),
    # site
    "ground": MaterialDef("#7E8478", roughness=0.97),
    "earth": MaterialDef("#8A7B62", roughness=0.99),
    "grass": MaterialDef("#65704F", roughness=0.99),
    "gravel": MaterialDef("#9A948A", roughness=0.98),
    "paving": MaterialDef("#A9A79E", roughness=0.95),
    "asphalt": MaterialDef("#4A4C4B", roughness=0.98),
}


def resolve_overrides(overrides: dict[str, str] | None) -> dict[str, MaterialDef]:
    """Apply ``{"material_key": "#hex"}`` colour overrides to the palette."""
    palette = dict(PALETTE)
    if not overrides:
        return palette
    for key, color in overrides.items():
        if key not in palette:
            continue
        if not isinstance(color, str):
            continue
        palette[key] = palette[key].with_color(color)
    return palette
