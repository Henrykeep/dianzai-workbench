# -*- coding: utf-8 -*-
# Source: https://github.com/devbisme/skidl@881a4d0f97ea0869e03501088245b8e21e4c2526 skidl/errors.py (MIT, unmodified below this line)

# The MIT License (MIT) - Copyright (c) Dave Vandenbout.

"""
Exceptions raised by SKiDL.

Schematic generation is done by the separate ``schematizer`` package, but
``Circuit.generate_schematic()`` translates its failures into the types defined
here so SKiDL callers only ever have to catch SKiDL's own exceptions.
"""

from .utilities import export_to_all


@export_to_all
class PlacementFailure(Exception):
    """Raised when the parts of a schematic cannot be placed."""

    pass


@export_to_all
class RoutingFailure(Exception):
    """Raised when the nets connecting the pins of a schematic cannot be routed."""

    pass
