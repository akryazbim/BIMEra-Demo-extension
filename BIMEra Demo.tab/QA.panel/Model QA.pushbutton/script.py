# -*- coding: utf-8 -*-
"""Model QA dashboard: rooms, views not on sheets, warnings, in-place families, imported CAD.
Filter the list, double-click to select and zoom, export to CSV. Reads only: changes nothing."""
import datetime
import logging
import os

from pyrevit import forms, revit, script
from pyrevit.framework import List
from System.Windows import Thickness, FontWeights
from System.Windows.Controls import Button, StackPanel, TextBlock, ComboBoxItem
from System.Windows.Media import SolidColorBrush, Color, FontFamily
from Autodesk.Revit import DB

from bimera_demo import qa

doc = revit.doc
uidoc = revit.uidoc

# Logging: a small log file (so a failed check can be investigated after the window is
# closed), with warnings and errors also shown by pyRevit's own logger.
# Note: script.get_logger() is pyRevit's wrapper, not a standard Python logger, so the
# file goes through Python's logging module instead.
LOG_DIR = os.path.join(os.environ["APPDATA"], "pyRevit", "BIMEra Demo")
LOG_FILE = os.path.join(LOG_DIR, "model_qa.log")


class QALog(object):
    def __init__(self):
        self.pyrevit = script.get_logger()
        self.file = logging.getLogger("BIMEra.ModelQA")
        self.file.setLevel(logging.INFO)
        if not self.file.handlers:  # pyRevit may reuse the engine: add the file once
            try:
                if not os.path.isdir(LOG_DIR):
                    os.makedirs(LOG_DIR)
                if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
                    os.remove(LOG_FILE)  # keep it small: start again after 1 MB
                handler = logging.FileHandler(LOG_FILE)
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                self.file.addHandler(handler)
            except Exception as err:
                self.pyrevit.warning("Could not open the QA log file: {}".format(err))

    def info(self, msg, *args):
        self.file.info(msg, *args)

    def warning(self, msg, *args):
        self.file.warning(msg, *args)
        self.pyrevit.warning(msg % args if args else msg)

    def error(self, msg, *args):
        self.file.error(msg, *args)
        self.pyrevit.error(msg % args if args else msg)


logger = QALog()


def brush(hex_color):
    c = hex_color.lstrip("#")
    return SolidColorBrush(Color.FromRgb(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)))


ALL = "All checks"


class QAWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, os.path.join(os.path.dirname(__file__), "ui.xaml"))
        self.subtitle.Text = doc.PathName or doc.Title
        self.tb_model.Text = doc.Title
        self.tb_date.Text = datetime.datetime.now().strftime("%d %b %Y %H:%M")
        self.rows = []
        self.run()

    # ---- checks ---------------------------------------------------------
    def run(self):
        logger.info("Model QA started on %s", doc.Title)
        self.rows, timings = qa.run_checks(doc, {"checks": qa.ALL_CHECKS}, logger)
        logger.info("Model QA finished: %d issue(s), timings %s", len(self.rows), timings)
        self.total_text.Text = "{} ISSUES".format(len(self.rows))
        self.build_cards()
        self.check_combo.Items.Clear()
        for name in [ALL] + qa.ALL_CHECKS + ([qa.FAILED] if self.count(qa.FAILED) else []):
            self.check_combo.Items.Add(name)
        self.check_combo.SelectedIndex = 0
        self.apply_filter()
        failed = self.count(qa.FAILED)
        if failed:
            self.status.Text = "{} check(s) could not run. Details: {}".format(failed, LOG_FILE)
            self.status.Foreground = brush("#C22F28")

    def count(self, check):
        return len([r for r in self.rows if r.Check == check])

    def build_cards(self):
        self.cards.Children.Clear()
        for name in qa.ALL_CHECKS:
            n = self.count(name)
            panel = StackPanel()
            big = TextBlock()
            big.Text = str(n)
            big.FontSize = 24
            big.FontWeight = FontWeights.Bold
            big.FontFamily = FontFamily("Archivo, Segoe UI")
            big.Foreground = brush("#C22F28") if n else brush("#1C62C2")
            label = TextBlock()
            label.Text = name.upper()
            label.FontSize = 10
            label.FontFamily = FontFamily("IBM Plex Mono, Consolas")
            panel.Children.Add(big)
            panel.Children.Add(label)
            card = Button()
            card.Style = self.FindResource("Card")
            card.Content = panel
            card.Tag = name
            card.Click += self.card_clicked
            self.cards.Children.Add(card)

    # ---- filtering ------------------------------------------------------
    def apply_filter(self):
        check = self.check_combo.SelectedItem or ALL
        text = (self.search_box.Text or "").strip().lower()
        shown = []
        for r in self.rows:
            if check != ALL and r.Check != check:
                continue
            if text and text not in u" ".join([r.Check, r.Problem, r.Name, r.Detail, r.IdText]).lower():
                continue
            shown.append(r)
        self.issues.ItemsSource = shown
        if not self.count(qa.FAILED):
            self.status.Text = "Showing {} of {}. Double-click a row, or select rows and click Select & zoom.".format(
                len(shown), len(self.rows))

    def filter_changed(self, sender, args):
        if getattr(self, "rows", None) is not None and hasattr(self, "issues"):
            self.apply_filter()

    def card_clicked(self, sender, args):
        self.check_combo.SelectedItem = sender.Tag

    # ---- actions ----------------------------------------------------------
    def zoom_clicked(self, sender, args):
        picked = list(self.issues.SelectedItems)
        if not picked:
            self.status.Text = "Select one or more rows first."
            return
        try:
            ids = []
            for row in picked:
                for i in row.Ids:
                    eid = qa.element_id(i)
                    if doc.GetElement(eid) is not None:
                        ids.append(eid)
            if not ids:
                self.status.Text = "Nothing to show: the element no longer exists (click Refresh)."
                return
            first = doc.GetElement(ids[0])
            if isinstance(first, DB.View) and len(ids) == 1:
                uidoc.RequestViewChange(first)  # a view: open it
                self.status.Text = u"Opening view '{}' (it opens when this window is closed).".format(first.Name)
                return
            uidoc.Selection.SetElementIds(List[DB.ElementId](ids))
            uidoc.ShowElements(List[DB.ElementId](ids))
            uidoc.RefreshActiveView()
            self.status.Text = "Selected {} element(s) in Revit.".format(len(ids))
        except Exception as err:
            logger.warning("Select & zoom failed: %s", err)
            self.status.Text = u"Revit could not show that element here: {}".format(err)

    def refresh_clicked(self, sender, args):
        self.search_box.Text = ""
        self.run()
        self.status.Text = "Refreshed: {} issue(s).".format(len(self.rows))

    def export_clicked(self, sender, args):
        rows = list(self.issues.ItemsSource or [])
        if not rows:
            self.status.Text = "Nothing to export."
            return
        default = u"{}_QA_{}.csv".format(doc.Title, datetime.datetime.now().strftime("%Y%m%d_%H%M"))
        path = forms.save_file(file_ext="csv", default_name=default)
        if not path:
            return
        try:
            n = qa.to_csv(rows, path)
            logger.info("Exported %d row(s) to %s", n, path)
            self.status.Text = u"Exported {} row(s) to {}".format(n, path)
        except Exception as err:
            logger.error("CSV export failed: %s", err)
            forms.alert(u"Could not write the CSV file (is it open in Excel?)\n\n{}".format(err),
                        title="Model QA")

    def close_clicked(self, sender, args):
        self.Close()


try:
    QAWindow().show_dialog()
except Exception as err:
    logger.error("Model QA could not start: %s", err)
    forms.alert(u"Model QA could not start:\n\n{}\n\nLog: {}".format(err, LOG_FILE), title="Model QA")
