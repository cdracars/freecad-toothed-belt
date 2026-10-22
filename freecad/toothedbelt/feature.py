"""Parametric ToothedBelt object (Part::FeaturePython).

The belt rebuilds itself whenever its path (usually a sketch) or any of its
properties change, through FreeCAD's normal recompute. Width accepts
expressions like any other Length property.
"""

import os

import FreeCAD as App

from . import geometry
from .profiles import DEFAULT_PROFILE, PROFILES

ICON = os.path.join(os.path.dirname(__file__), "resources", "icons", "ToothedBelt.svg")

# Warn when a closed loop is off a whole number of teeth by more than this.
PITCH_ERROR_WARN_MM = 0.01


def _add(obj, kind, name, group, doc, default=None, read_only=False):
    if name in obj.PropertiesList:
        return False
    obj.addProperty(kind, name, group, doc)
    if default is not None:
        setattr(obj, name, default)
    if read_only:
        obj.setEditorMode(name, 1)
    return True


class ToothedBelt:
    TYPE = "ToothedBelt::Belt"

    def __init__(self, obj):
        obj.Proxy = self
        self._init_properties(obj)

    def _init_properties(self, obj):
        _add(obj, "App::PropertyLink", "Path", "Belt",
             "Sketch (or other planar wire) to use as the belt's pitch line")
        _add(obj, "App::PropertyInteger", "WireIndex", "Belt",
             "Which wire of the path to use when it contains more than one", 0)
        if _add(obj, "App::PropertyEnumeration", "Profile", "Belt", "Tooth profile"):
            obj.Profile = list(PROFILES)
            obj.Profile = DEFAULT_PROFILE
        if _add(obj, "App::PropertyEnumeration", "TeethSide", "Belt",
                "Inside/Outside of a closed loop; on an open path Inside is the left of "
                "the path direction. Both makes a double-sided belt."):
            obj.TeethSide = list(geometry.SIDES)
            obj.TeethSide = "Inside"
        _add(obj, "App::PropertyLength", "Width", "Belt", "Belt width", 6.0)
        _add(obj, "App::PropertyBool", "Symmetric", "Belt",
             "Extrude the width symmetrically about the sketch plane", True)
        _add(obj, "App::PropertyBool", "RootFillets", "Belt",
             "Add root fillets between teeth and backing (adjusted for path curvature)", True)

        _add(obj, "App::PropertyInteger", "ToothCount", "Result", "Number of teeth", 0, True)
        _add(obj, "App::PropertyLength", "PathLength", "Result", "Pitch line length", 0.0, True)
        _add(obj, "App::PropertyDistance", "PitchError", "Result",
             "Closed loops: path length minus ToothCount x pitch. Non-zero means the "
             "sketched loop is not a real belt length; the teeth are spread to fit.", 0.0, True)

    def onDocumentRestored(self, obj):
        self._init_properties(obj)

    def execute(self, obj):
        if obj.Path is None:
            return
        wire = geometry.pick_wire(obj.Path.Shape, obj.WireIndex)
        normal = geometry.path_normal(wire, obj.Path)
        try:
            result = geometry.build_belt(
                wire, normal,
                profile=obj.Profile,
                side=obj.TeethSide,
                width=float(obj.Width.Value),
                symmetric=obj.Symmetric,
                fillets=obj.RootFillets,
            )
        except geometry.BeltError as exc:
            App.Console.PrintError(f"{obj.Label}: {exc}\n")
            raise
        obj.Shape = result.shape
        obj.ToothCount = result.tooth_count
        obj.PathLength = result.path_length
        obj.PitchError = result.pitch_error
        if result.closed and abs(result.pitch_error) > PITCH_ERROR_WARN_MM:
            pitch = PROFILES[obj.Profile].pitch
            App.Console.PrintWarning(
                f"{obj.Label}: loop is {result.path_length:.3f} mm, which is not a whole number "
                f"of {pitch} mm teeth ({result.pitch_error:+.3f} mm off). Nearest real belt: "
                f"{result.tooth_count}T = {result.tooth_count * pitch:.1f} mm; teeth were spread "
                f"to fit.\n")

    # FreeCAD >= 0.22 / 1.x
    def dumps(self):
        return None

    def loads(self, state):
        return None

    # Older FreeCAD
    __getstate__ = dumps

    def __setstate__(self, state):
        return None


class ViewProviderToothedBelt:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

    def claimChildren(self):
        path = getattr(self.Object, "Path", None)
        return [path] if path is not None else []

    def onDelete(self, vobj, subelements):
        path = getattr(vobj.Object, "Path", None)
        if path is not None and hasattr(path, "ViewObject") and path.ViewObject:
            path.ViewObject.Visibility = True
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps

    def __setstate__(self, state):
        return None


def make_belt(path_obj, profile=DEFAULT_PROFILE, teeth_side="Inside", width=6.0,
              symmetric=True, root_fillets=True, name="ToothedBelt", doc=None):
    """Create a ToothedBelt in ``doc`` (default: active document) following ``path_obj``."""
    doc = doc or App.ActiveDocument
    if doc is None:
        raise RuntimeError("no active document")
    obj = doc.addObject("Part::FeaturePython", name)
    ToothedBelt(obj)
    obj.Path = path_obj
    obj.Profile = profile
    obj.TeethSide = teeth_side
    obj.Width = width
    obj.Symmetric = symmetric
    obj.RootFillets = root_fillets
    if App.GuiUp:
        ViewProviderToothedBelt(obj.ViewObject)
        if hasattr(path_obj, "ViewObject") and path_obj.ViewObject:
            path_obj.ViewObject.Visibility = False
    return obj
