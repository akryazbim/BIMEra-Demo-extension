# -*- coding: utf-8 -*-
"""Sheet Standardiser logic (no user interface here, so it can be tested on its own).

plan_renames(doc, rules)  -> list of rows, reads the model only
apply_renames(doc, rows, tx_name) -> number of sheets renamed, one transaction

Works in IronPython 2.7 (pyRevit's default engine) and Revit 2027 (ElementId.Value).
"""
import System
from Autodesk.Revit import DB

FT_TO_MM = 304.8

OK = "OK"
RENAME = "Rename"
REVIEW = "For review"


def element_id(value):
    """ElementId from a stored integer (Revit 2027 ids are 64-bit)."""
    return DB.ElementId(System.Int64(value))


def _storey_index_by_level(doc, rules):
    """Map level id -> (index, storey word, is_roof) or (None, reason) for levels we can't map."""
    levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level),
                    key=lambda lv: lv.Elevation)
    tol = rules.get("ground_tolerance_mm", 1.0) / FT_TO_MM
    ground = [i for i, lv in enumerate(levels) if abs(lv.Elevation) <= tol]
    roof_word = rules.get("roof_match", "roof").lower()
    words = rules["storey_words"]
    result = {}
    if not ground:
        for lv in levels:
            result[lv.Id.Value] = (None, "no level at elevation 0, so storeys can't be counted")
        return result
    g = ground[0]
    top = len(levels) - 1
    for i, lv in enumerate(levels):
        index = i - g
        is_roof = (i == top and roof_word in lv.Name.lower())
        if is_roof:
            result[lv.Id.Value] = (index, None, True)
        elif roof_word in lv.Name.lower():
            result[lv.Id.Value] = (None, "roof-named level is not the top level")
        elif index < 0:
            result[lv.Id.Value] = (None, "below ground, the standard has no rule for it")
        elif index >= len(words):
            result[lv.Id.Value] = (None, "no storey word for index {}".format(index))
        else:
            result[lv.Id.Value] = (index, words[index], False)
    return result


def _plan_levels_on_sheet(doc, sheet, view_types):
    levels = {}
    for vid in sheet.GetAllPlacedViews():
        view = doc.GetElement(vid)
        if isinstance(view, DB.ViewPlan) and str(view.ViewType) in view_types and view.GenLevel:
            levels[view.GenLevel.Id.Value] = view.GenLevel
    return list(levels.values())


def plan_renames(doc, rules):
    """Return one row per sheet: what it is now, what the standard wants, and the status."""
    storeys = _storey_index_by_level(doc, rules)
    view_types = rules.get("plan_view_types", ["FloorPlan"])
    rows = []
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
              if not s.IsPlaceholder]
    for sheet in sorted(sheets, key=lambda s: s.SheetNumber):
        row = {"id": sheet.Id.Value, "number": sheet.SheetNumber, "name": sheet.Name,
               "level": "", "new_number": "", "new_name": "", "status": REVIEW, "note": ""}
        rows.append(row)
        levels = _plan_levels_on_sheet(doc, sheet, view_types)
        if not levels:
            row["note"] = "no floor plan on this sheet"
            continue
        if len(levels) > 1:
            row["note"] = "plans of {} levels on one sheet".format(len(levels))
            row["level"] = ", ".join(lv.Name for lv in levels)
            continue
        level = levels[0]
        row["level"] = level.Name
        info = storeys.get(level.Id.Value)
        if info is None or info[0] is None:
            row["note"] = info[1] if info else "level not found"
            continue
        index, word, is_roof = info
        number = rules["number_pattern"].format(number=rules["number_start"] + index)
        name = rules["roof_sheet_name"] if is_roof else rules["name_pattern"].format(storey=word)
        row["new_number"], row["new_name"] = number, name
        if number == sheet.SheetNumber and name == sheet.Name:
            row["status"] = OK
        else:
            row["status"] = RENAME

    # Two sheets can't share a number: send both to review.
    wanted = {}
    for row in rows:
        if row["new_number"]:
            wanted.setdefault(row["new_number"], []).append(row)
    for number, group in wanted.items():
        if len(group) > 1:
            for row in group:
                row["status"] = REVIEW
                row["note"] = "{} sheets would get number {}".format(len(group), number)
    # A sheet we are not renaming may already hold the number we want.
    kept = dict((r["number"], r) for r in rows if r["status"] != RENAME)
    for row in rows:
        holder = kept.get(row["new_number"])
        if row["status"] == RENAME and holder is not None and holder is not row:
            row["status"] = REVIEW
            row["note"] = "number {} is held by sheet '{}', which keeps it".format(
                row["new_number"], holder["name"])
    return rows


def apply_renames(doc, rows, tx_name):
    """Rename the 'Rename' rows in one transaction (one undo step). Returns the count.

    Pass 1 gives every sheet a temporary unique number, pass 2 the final one,
    so two sheets can swap numbers without a 'number already in use' error.
    Any error rolls everything back and is raised to the caller.
    """
    todo = [r for r in rows if r["status"] == RENAME]
    if not todo:
        return 0
    tx = DB.Transaction(doc, tx_name)
    tx.Start()
    try:
        sheets = []
        for row in todo:
            sheet = doc.GetElement(element_id(row["id"]))
            sheet.SheetNumber = "BMRTMP-{}".format(row["id"])
            sheets.append((sheet, row))
        for sheet, row in sheets:
            sheet.SheetNumber = row["new_number"]
            sheet.Name = row["new_name"]
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise Exception("Revit did not commit the change, nothing was renamed.")
    except Exception:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        raise
    return len(todo)
