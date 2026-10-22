"""Make the package importable with or without FreeCAD.

Pure-math tests run under any Python 3.9+. FreeCAD tests run when FreeCAD's
Python modules are importable; point FREECAD_LIB at the directory holding
FreeCAD.so / FreeCAD.pyd (for a conda install, ``$CONDA_PREFIX/lib``).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_PARENT = os.path.join(ROOT, "freecad")

lib = os.environ.get("FREECAD_LIB")
if lib and lib not in sys.path:
    sys.path.append(lib)

try:
    import FreeCAD  # noqa: F401

    import freecad  # FreeCAD's own namespace package; extend it like an installed addon

    if PKG_PARENT not in freecad.__path__:
        freecad.__path__.append(PKG_PARENT)
except ImportError:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
