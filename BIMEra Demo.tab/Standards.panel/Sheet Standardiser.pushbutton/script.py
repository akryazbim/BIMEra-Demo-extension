# -*- coding: utf-8 -*-
"""Renames every sheet's number and name to the project standard.
Preview first, then one undoable step. Rules: sheet_rules.json (Shift+click to edit)."""
import io
import json
import os

from pyrevit import forms, revit, script
from bimera_demo import sheets

doc = revit.doc
output = script.get_output()
output.set_title("Sheet Standardiser")

# 1. Read the rules that sit next to this script.
rules_file = os.path.join(os.path.dirname(__file__), "sheet_rules.json")
try:
    with io.open(rules_file, encoding="utf-8") as f:
        rules = json.load(f)
except Exception as err:
    forms.alert("Can't read the rules file:\n{}\n\n{}".format(rules_file, err), exitscript=True)

# 2. Work out what each sheet should be called (reads only, changes nothing).
rows = sheets.plan_renames(doc, rules)
if not rows:
    forms.alert("This model has no sheets.", exitscript=True)

to_rename = [r for r in rows if r["status"] == sheets.RENAME]
to_review = [r for r in rows if r["status"] == sheets.REVIEW]

# 3. Preview in the output window. Click a sheet id to open it.
output.print_md("## Sheet Standardiser: preview")
output.print_md("Rules: `{}`".format(rules_file))
output.print_table(
    [[output.linkify(sheets.element_id(r["id"]), r["number"]), r["name"], r["level"],
      r["new_number"], r["new_name"], r["status"], r["note"]] for r in rows],
    columns=["Sheet", "Current name", "Plan level", "New number", "New name", "Status", "Note"])
output.print_md("**{}** to rename, **{}** already OK, **{}** for review (left as they are).".format(
    len(to_rename), len(rows) - len(to_rename) - len(to_review), len(to_review)))

if not to_rename:
    forms.alert("Nothing to rename: every sheet that can be checked already follows the standard."
                + ("\n\n{} sheet(s) need a person to look at them (see the output window)."
                   .format(len(to_review)) if to_review else ""))
    script.exit()

# 4. Ask before changing anything.
if not forms.alert("Rename {} sheet(s) as shown in the output window?\n\n"
                   "It is one step: Ctrl+Z undoes all of it.".format(len(to_rename)),
                   title="Sheet Standardiser", yes=True, no=True):
    script.exit()

# 5. Apply in one transaction. Any error rolls everything back.
try:
    count = sheets.apply_renames(doc, rows, "BIMEra: Standardise sheets")
except Exception as err:
    forms.alert("Nothing was changed. Revit reported:\n\n{}".format(err), title="Sheet Standardiser")
    script.exit()

output.print_md("### Done: renamed {} sheet(s). Undo with Ctrl+Z (one step).".format(count))
