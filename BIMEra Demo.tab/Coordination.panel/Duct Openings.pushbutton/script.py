# -*- coding: utf-8 -*-
"""Finds where ducts pass through walls and cuts an opening (duct size + clearance) at each one.
Uses the selected ducts, or every duct if none is selected. Safe to run again: no duplicates."""
import io
import json
import os

from pyrevit import forms, revit, script
from bimera_demo import openings

doc = revit.doc
output = script.get_output()
output.set_title("Duct Openings")
here = os.path.dirname(__file__)

# 1. Settings and the opening family both sit next to this script.
try:
    with io.open(os.path.join(here, "opening_settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
except Exception as err:
    forms.alert("Can't read opening_settings.json:\n{}".format(err), exitscript=True)
rfa = os.path.join(here, settings.get("family_file", "BIMEra_Wall_Opening.rfa"))
if not os.path.exists(rfa):
    forms.alert("The opening family is missing:\n" + rfa, exitscript=True)

# 2. Which ducts? The selected ones, otherwise all of them.
selected = [e for e in revit.get_selection()
            if e.Category and e.Category.Id.Value == int(revit.DB.BuiltInCategory.OST_DuctCurves)]
scope = "the {} selected duct(s)".format(len(selected)) if selected else "every duct in the model"

# 3. Find the clashes (reads only, changes nothing).
rows = openings.plan_openings(doc, settings, selected or None)
new = [r for r in rows if r["status"] == openings.NEW]
done = [r for r in rows if r["status"] == openings.EXISTS]
skipped = [r for r in rows if r["status"] == openings.SKIP]

output.print_md("## Duct Openings: preview")
output.print_md("Checked {}. Clearance {} mm each side.".format(scope, settings.get("clearance_mm", 50)))
if rows:
    output.print_table(
        [[output.linkify(openings.element_id(r["wall"]), r["wall_mark"] or "wall"),
          output.linkify(openings.element_id(r["duct"]), r["duct_mark"] or "duct") if r["duct"] else "",
          r.get("duct_size", ""), r.get("size", ""), r["status"], r["note"]] for r in rows],
        columns=["Wall", "Duct", "Duct size", "Opening (W x H mm)", "Status", "Note"])
output.print_md("**{}** new, **{}** already have an opening, **{}** skipped.".format(
    len(new), len(done), len(skipped)))

if not new:
    forms.alert("No new openings needed.\n\n{} clash(es) already have an opening.".format(len(done))
                if done else "No duct passes through a wall in {}.".format(scope))
    script.exit()

if not forms.alert("Create {} opening(s) as listed in the output window?\n\n"
                   "It is one step: Ctrl+Z undoes all of it.".format(len(new)),
                   title="Duct Openings", yes=True, no=True):
    script.exit()

# 4. Create them in one transaction. Any error rolls everything back.
try:
    created = openings.apply_openings(doc, rows, rfa, settings, "BIMEra: Duct openings")
except Exception as err:
    forms.alert("Nothing was changed. Revit reported:\n\n{}".format(err), title="Duct Openings")
    script.exit()

output.print_md("### Done: {} opening(s) created. Undo with Ctrl+Z (one step).".format(len(created)))
output.print_md("Select them all: {}".format(
    output.linkify([openings.element_id(i) for i in created], "{} new openings".format(len(created)))))
