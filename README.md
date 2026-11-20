# BIMEra Demo (pyRevit extension, Revit 2027)

Three example tools from the BIMEra "AI for BIM Professionals" course, Session 5. Written with AI, tested on Revit 2027.3 with pyRevit 7.0.1.

| Panel | Button | What it does | Changes the model? |
|---|---|---|---|
| Standards | Sheet Standardiser | Renames sheet numbers and names to the standard in `sheet_rules.json` (default: A-101 Ground Floor Plan, A-102 First Floor Plan, ..., Roof Plan). Preview first. | Yes, one Ctrl+Z undoes it |
| Coordination | Duct Openings | Cuts an opening (duct + 50 mm each side) wherever a duct passes through a wall, with the `BIMEra_Wall_Opening.rfa` family. No duplicates on a second run. | Yes, one Ctrl+Z undoes it |
| QA | Model QA | Dashboard: rooms not placed / not enclosed / no name, views not on sheets, warnings, in-place families, imported CAD. Filter, zoom, CSV export. | No (reads only) |

Shift+click Sheet Standardiser or Duct Openings to open its settings file.

## Install

Option 1, from Git (needs pyRevit 7; Git itself is not needed):

    pyrevit extend ui "BIMEra Demo" <repository URL>

Update later with `pyrevit extensions update "BIMEra Demo"`, then Reload in Revit.

Option 2, from a shared folder: put this folder inside a shared folder, then

    pyrevit extensions paths add "<the shared folder>"

and Reload pyRevit.

## Use at your own risk

Run new tools on a copy of your model first. These are teaching examples, not certified production tools.

## Versions

- 1.0 (20 Nov 2026): first version.
