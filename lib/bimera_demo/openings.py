# -*- coding: utf-8 -*-
"""Duct-wall clash openings logic (no user interface here, so it can be tested on its own).

plan_openings(doc, settings, ducts=None) -> list of rows, reads the model only
apply_openings(doc, rows, rfa_path, settings, tx_name) -> list of new opening ids

Simple geometry on purpose: a clash is where a straight duct's centreline crosses a
straight wall's centre plane, between the wall's ends and below its top. The opening
is the duct size plus a clearance on every side, made with a small wall-hosted void
family (BIMEra_Wall_Opening.rfa, instance parameters Width and Height).

IronPython 2.7 (pyRevit's default engine), Revit 2027 API (ElementId.Value).
"""
import math
import clr
import System
from Autodesk.Revit import DB

MM = 1 / 304.8
TAG = "BIMEra opening for duct {}"

NEW = "New"
EXISTS = "Already has opening"
SKIP = "Skipped"


def element_id(value):
    """ElementId from a stored integer (Revit 2027 ids are 64-bit)."""
    return DB.ElementId(System.Int64(value))


_id = element_id


def _mark(element):
    p = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
    return (p.AsString() if p else None) or ""


def _duct_size_mm(duct):
    """(width, height, label) in mm. Round ducts are treated as a square of the diameter."""
    d = duct.get_Parameter(DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
    if d is not None and d.HasValue and d.AsDouble() > 0:
        dia = d.AsDouble() / MM
        # Escape, not a literal: keeps the source file plain ASCII for IronPython.
        return dia, dia, u"Ø{:.0f}".format(dia)
    w = duct.get_Parameter(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM).AsDouble() / MM
    h = duct.get_Parameter(DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM).AsDouble() / MM
    return w, h, u"{:.0f}x{:.0f}".format(w, h)


def _round_up(value, step):
    return int(math.ceil(value / float(step)) * step) if step else value


def _existing_openings(doc, family_name):
    """Opening instances already in the model, grouped by host wall id."""
    by_wall = {}
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        if inst.Symbol.FamilyName == family_name and inst.Host is not None:
            by_wall.setdefault(inst.Host.Id.Value, []).append(inst)
    return by_wall


def _crossing(wall, duct_line):
    """Where the duct centreline crosses the wall's centre plane, or (None, reason)."""
    wl = wall.Location.Curve
    p0, p1 = wl.GetEndPoint(0), wl.GetEndPoint(1)
    along = DB.XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize()
    normal = DB.XYZ(-along.Y, along.X, 0)
    q0, q1 = duct_line.GetEndPoint(0), duct_line.GetEndPoint(1)
    dq = q1 - q0
    denom = dq.DotProduct(normal)
    if abs(denom) < 1e-9:
        return None, "parallel"
    t = (p0 - q0).DotProduct(normal) / denom
    if t < 0 or t > 1:
        return None, "duct ends before the wall"
    x = q0 + dq.Multiply(t)
    s = DB.XYZ(x.X - p0.X, x.Y - p0.Y, 0).DotProduct(along)
    if s < 0 or s > wl.Length:
        return None, "beyond the wall ends"
    bb = wall.get_BoundingBox(None)
    if x.Z < bb.Min.Z or x.Z > bb.Max.Z:
        return None, "above or below the wall"
    flat = DB.XYZ(dq.X, dq.Y, 0)
    sin_angle = abs(flat.Normalize().DotProduct(normal)) if flat.GetLength() > 1e-9 else 0
    on_line = DB.XYZ(p0.X, p0.Y, 0) + along.Multiply(s)
    return {"point": DB.XYZ(on_line.X, on_line.Y, x.Z), "s": s, "length": wl.Length,
            "sin": sin_angle, "top": bb.Max.Z, "bottom": bb.Min.Z}, None


def plan_openings(doc, settings, ducts=None):
    """One row per duct-wall clash (and per wall/duct that had to be skipped)."""
    clearance = float(settings.get("clearance_mm", 50))
    step = settings.get("round_up_to_mm", 10)
    min_sin = math.sin(math.radians(settings.get("min_angle_deg", 30)))
    family_name = settings.get("family_name", "BIMEra_Wall_Opening")
    tol = settings.get("duplicate_tolerance_mm", 50) * MM

    if ducts is None:
        ducts = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_DuctCurves)
                     .WhereElementIsNotElementType())
    rows = []
    walls = []
    for wall in DB.FilteredElementCollector(doc).OfClass(DB.Wall):
        if wall.WallType.Kind != DB.WallKind.Basic:
            continue  # curtain and stacked walls: no rule for them in this simple tool
        if not isinstance(getattr(wall.Location, "Curve", None), DB.Line):
            rows.append({"wall": wall.Id.Value, "wall_mark": _mark(wall), "duct": None, "duct_mark": "",
                         "status": SKIP, "note": "curved wall, not checked", "size": ""})
            continue
        walls.append(wall)
    existing = _existing_openings(doc, family_name)

    for duct in ducts:
        line = getattr(duct.Location, "Curve", None)
        if not isinstance(line, DB.Line):
            continue
        w_mm, h_mm, label = _duct_size_mm(duct)
        for wall in walls:
            hit, _ = _crossing(wall, line)
            if hit is None:
                continue
            row = {"wall": wall.Id.Value, "wall_mark": _mark(wall), "duct": duct.Id.Value,
                   "duct_mark": _mark(duct), "duct_size": label, "status": NEW, "note": "",
                   "x": hit["point"].X, "y": hit["point"].Y, "z": hit["point"].Z}
            rows.append(row)
            if hit["sin"] < min_sin:
                row["status"], row["note"] = SKIP, "duct crosses the wall at a shallow angle"
                continue
            width = _round_up(w_mm / hit["sin"] + 2 * clearance, step)
            height = _round_up(h_mm + 2 * clearance, step)
            row["width_mm"], row["height_mm"] = width, height
            row["size"] = "{} x {}".format(width, height)
            bottom = hit["point"].Z - height / 2.0 * MM
            row["bottom_z"] = bottom
            if bottom < hit["bottom"] or bottom + height * MM > hit["top"]:
                row["note"] = "opening reaches past the wall's top or base"
            if hit["s"] < width / 2.0 * MM or hit["s"] > hit["length"] - width / 2.0 * MM:
                row["note"] = "opening reaches past the wall's end"
            for inst in existing.get(wall.Id.Value, []):
                tagged = (inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or "") \
                    == TAG.format(duct.Id.Value)
                lp = inst.Location.Point
                near = DB.XYZ(lp.X, lp.Y, 0).DistanceTo(DB.XYZ(hit["point"].X, hit["point"].Y, 0)) < tol \
                    and abs(lp.Z - bottom) < tol
                if tagged or near:
                    row["status"], row["note"] = EXISTS, "opening {} already there".format(inst.Id.Value)
                    row["opening"] = inst.Id.Value
                    break
    return rows


def _get_symbol(doc, rfa_path, family_name):
    for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if sym.FamilyName == family_name:
            return sym
    # IronPython would otherwise pick the LoadFamily(path) overload that returns only a bool.
    ref = clr.Reference[DB.Family]()
    loaded = doc.LoadFamily(rfa_path, ref)
    family = ref.Value
    if not loaded or family is None:
        raise Exception("Could not load the opening family from:\n" + rfa_path)
    return doc.GetElement(list(family.GetFamilySymbolIds())[0])


def apply_openings(doc, rows, rfa_path, settings, tx_name):
    """Create one opening per 'New' row in ONE transaction (one undo). Returns new ids.

    Loads the family if needed, places it on the wall, sizes it, tags it with the
    duct id (so a second run finds it), and makes the void cut the wall.
    Any error rolls everything back and is raised to the caller.
    """
    todo = [r for r in rows if r["status"] == NEW]
    if not todo:
        return []
    family_name = settings.get("family_name", "BIMEra_Wall_Opening")
    created = []
    tx = DB.Transaction(doc, tx_name)
    tx.Start()
    try:
        symbol = _get_symbol(doc, rfa_path, family_name)
        if not symbol.IsActive:
            symbol.Activate()
            doc.Regenerate()
        for row in todo:
            wall = doc.GetElement(_id(row["wall"]))
            level = doc.GetElement(wall.LevelId)
            point = DB.XYZ(row["x"], row["y"], row["bottom_z"])
            inst = doc.Create.NewFamilyInstance(point, symbol, wall, level,
                                                DB.Structure.StructuralType.NonStructural)
            inst.LookupParameter("Width").Set(row["width_mm"] * MM)
            inst.LookupParameter("Height").Set(row["height_mm"] * MM)
            inst.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM).Set(row["bottom_z"] - level.Elevation)
            inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(TAG.format(row["duct"]))
            DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, inst)
            row["opening"] = inst.Id.Value
            created.append(inst.Id.Value)
        if tx.Commit() != DB.TransactionStatus.Committed:
            raise Exception("Revit did not commit the change, no openings were created.")
    except Exception:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        for row in todo:
            row.pop("opening", None)
        raise
    return created
