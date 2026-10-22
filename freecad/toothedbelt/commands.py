import FreeCAD as App
import FreeCADGui as Gui

from . import feature


class CreateToothedBelt:
    def GetResources(self):
        return {
            "Pixmap": feature.ICON,
            "MenuText": "Toothed belt",
            "ToolTip": "Create a timing belt (GT2, GT1.5, HTD 5M, HTD 8M) along the selected "
                       "sketch. Draw the sketch on the belt's pitch line.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape")]
        if len(sel) != 1:
            App.Console.PrintError("Toothed belt: select exactly one sketch (the pitch line) first.\n")
            return
        doc = App.ActiveDocument
        doc.openTransaction("Create toothed belt")
        try:
            obj = feature.make_belt(sel[0], doc=doc)
            doc.recompute()
        finally:
            doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)


Gui.addCommand("ToothedBelt_Create", CreateToothedBelt())
