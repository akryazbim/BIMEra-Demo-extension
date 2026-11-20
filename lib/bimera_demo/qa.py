# -*- coding: utf-8 -*-
"""Model QA checks (no user interface here, so they can be tested on their own).

run_checks(doc, options, log) -> list of Issue rows. Read-only: changes nothing.
Each check runs on its own: if one fails, the others still run and the failure
becomes a row ("Check failed") plus a log entry with the traceback.

IronPython 2.7 (pyRevit's default engine), Revit 2027 API (ElementId.Value).
"""
import time
import traceback

import System
from Autodesk.Revit import DB

ROOMS = "Rooms"
VIEWS = "Views not on sheets"
WARNINGS = "Warnings"
INPLACE = "In-place families"
CAD = "Imported CAD"
FAILED = "Check failed"

ALL_CHECKS = [ROOMS, VIEWS, WARNINGS, INPLACE, CAD]

# View types that can go on a sheet (others, like the project browser, can't).
PLACEABLE = set(["FloorPlan", "CeilingPlan", "Elevation", "Section", "ThreeD", "DraftingView",
                 "Detail", "AreaPlan", "EngineeringPlan", "Schedule", "Rendering", "Walkthrough"])


def element_id(value):
    """ElementId from a stored integer (Revit 2027 ids are 64-bit)."""
    return DB.ElementId(System.Int64(value))


class Issue(object):
    """One row in the QA list. Plain attributes so WPF can bind to them."""

    def __init__(self, check, problem, name, detail="", ids=None, severity="Warning"):
        self.Check = check
        self.Problem = problem
        self.Name = name
        self.Detail = detail
        self.Ids = list(ids or [])
        self.IdText = ", ".join(str(i) for i in self.Ids[:3]) + (" ..." if len(self.Ids) > 3 else "")
        self.Severity = severity


def _room_name(room):
    p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    return (p.AsString() if p else "") or ""


def check_rooms(doc, options):
    rows = []
    rooms = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
    for room in rooms:
        label = u"{} {}".format(room.Number or "", _room_name(room)).strip() or "(no number)"
        level = room.Level.Name if room.Level else ""
        if room.Location is None:
            rows.append(Issue(ROOMS, "Not placed", label, "In the model but not placed in any plan", [room.Id.Value]))
        elif room.Area <= 0:
            rows.append(Issue(ROOMS, "Not enclosed", label, u"Placed on {} but has no boundary (area 0)".format(level),
                              [room.Id.Value], "Error"))
        if room.Location is not None and _room_name(room).strip() in ("", "Room"):
            rows.append(Issue(ROOMS, "No name", label, u"On {}".format(level), [room.Id.Value]))
    return rows


def check_views(doc, options):
    on_sheet = set()
    for vp in DB.FilteredElementCollector(doc).OfClass(DB.Viewport):
        on_sheet.add(vp.ViewId.Value)
    for ss in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance):
        on_sheet.add(ss.ScheduleId.Value)
    rows = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if view.IsTemplate or str(view.ViewType) not in PLACEABLE or view.Id.Value in on_sheet:
            continue
        if isinstance(view, DB.ViewSchedule) and (view.IsTitleblockRevisionSchedule or view.IsInternalKeynoteSchedule):
            continue
        if isinstance(view, DB.View3D) and view.Name.startswith("{"):
            continue  # Revit's own per-user {3D} views
        rows.append(Issue(VIEWS, str(view.ViewType), view.Name, "Not placed on any sheet", [view.Id.Value], "Info"))
    return rows


def check_warnings(doc, options):
    rows = []
    for w in doc.GetWarnings():
        ids = [i.Value for i in w.GetFailingElements()] + [i.Value for i in w.GetAdditionalElements()]
        text = w.GetDescriptionText()
        names = []
        for i in ids[:2]:
            el = doc.GetElement(element_id(i))
            if el is not None:
                cat = el.Category.Name if el.Category else el.GetType().Name
                names.append(u"{} {}".format(cat, i))
        rows.append(Issue(WARNINGS, text, u" / ".join(names) or "(no elements)", "", ids,
                          "Error" if w.GetSeverity() == DB.FailureSeverity.Error else "Warning"))
    return rows


def check_inplace(doc, options):
    rows = []
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        fam = inst.Symbol.Family
        if fam.IsInPlace:
            cat = inst.Category.Name if inst.Category else ""
            rows.append(Issue(INPLACE, cat, fam.Name, "In-place family: hard to reuse and schedule",
                              [inst.Id.Value], "Info"))
    return rows


def check_cad(doc, options):
    rows = []
    for imp in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
        if imp.IsLinked:
            continue  # linked CAD is normal practice; imported CAD is the problem
        tp = doc.GetElement(imp.GetTypeId())
        name = tp.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if tp else "CAD"
        owner = doc.GetElement(imp.OwnerViewId) if imp.ViewSpecific else None
        rows.append(Issue(CAD, "Imported (not linked)", name or "CAD",
                          u"In view {}".format(owner.Name) if owner else "Placed in 3D (all views)",
                          [imp.Id.Value]))
    return rows


CHECKS = {ROOMS: check_rooms, VIEWS: check_views, WARNINGS: check_warnings, INPLACE: check_inplace, CAD: check_cad}


def run_checks(doc, options, log):
    """options = {"checks": [names...]}. Returns (rows, timings)."""
    rows, timings = [], {}
    for name in options.get("checks", ALL_CHECKS):
        start = time.time()
        try:
            found = CHECKS[name](doc, options)
            rows.extend(found)
            log.info(u"%s: %d issue(s) in %.2f s", name, len(found), time.time() - start)
        except Exception as err:
            log.error(u"%s check failed:\n%s", name, traceback.format_exc())
            rows.append(Issue(FAILED, name, u"The check could not run", u"{}".format(err), [], "Error"))
        timings[name] = round(time.time() - start, 2)
    return rows, timings


def to_csv(rows, path):
    """Write the rows to a CSV that Excel opens correctly (UTF-8 with BOM)."""
    import io

    def q(value):
        text = u"{}".format(value)
        if any(c in text for c in u',"\n\r'):
            text = u'"' + text.replace(u'"', u'""') + u'"'
        return text
    # Write the BOM once ourselves: IronPython's "utf-8-sig" writer repeats it on every write.
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(u"﻿Check,Severity,Problem,Element,Detail,Element ids\r\n")
        for r in rows:
            f.write(u",".join(q(v) for v in (r.Check, r.Severity, r.Problem, r.Name, r.Detail,
                                             u" ".join(str(i) for i in r.Ids))) + u"\r\n")
    return len(rows)
