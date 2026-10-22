import os

import FreeCADGui as Gui

ICON = os.path.join(os.path.dirname(__file__), "resources", "icons", "ToothedBelt.svg")


class ToothedBeltWorkbench(Gui.Workbench):
    MenuText = "Toothed Belt"
    ToolTip = "Parametric timing belts along a sketch path"
    Icon = ICON

    def Initialize(self):
        from . import commands  # noqa: F401  (registers the command)

        self.appendToolbar("Toothed Belt", ["ToothedBelt_Create"])
        self.appendMenu("Toothed Belt", ["ToothedBelt_Create"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ToothedBeltWorkbench())
