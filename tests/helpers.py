from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import MapDocument


def doc_with_block(mins=(0, 0, 0), maxs=(64, 64, 64)):
    doc = MapDocument()
    stack = CommandStack(doc)
    solids = solids_from_faces(doc, primitives.block(mins, maxs))
    stack.push(AddObjects(solids))
    return doc, stack, solids[0]
