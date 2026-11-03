"""Vorlagen: fertige Objektgruppen (Startraum, Surf-Map aus dem Assistenten)."""
from .room_map import (
           LINEAR_ROOMS,
           STAGE_ROOMS,
           RoomMapSettings,
           RoomSpec,
           new_room_map,
           plan_room_map,
)
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

__all__ = ["LINEAR_ROOMS", "STAGE_ROOMS", "RoomMapSettings", "RoomSpec", "new_room_map", "plan_room_map",
           "LAYOUTS", "RAMP_KINDS", "CourseSpec", "PlanItem", "SPAWN_CLASSES", "SurfMapSettings", "enclose_map", "hull_around", "new_surf_map", "plan_surf_map",
           "starter_room"]
