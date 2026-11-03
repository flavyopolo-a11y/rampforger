"""Vorlagen: fertige Objektgruppen (Startraum, Surf-Map aus dem Assistenten)."""
from .starter import SPAWN_CLASSES, enclose_map, hull_around, starter_room
from .surf_map import (
           LAYOUTS,
           RAMP_KINDS,
           CourseSpec,
           PlanItem,
           SurfMapSettings,
           new_surf_map,
           plan_surf_map,
)

__all__ = ["LAYOUTS", "RAMP_KINDS", "CourseSpec", "PlanItem", "SPAWN_CLASSES", "SurfMapSettings", "enclose_map", "hull_around", "new_surf_map", "plan_surf_map",
           "starter_room"]
