# -*- coding: utf-8 -*-
"""Shift+click: open the rules file in Notepad so you can change the standard."""
import os
os.startfile(os.path.join(os.path.dirname(__file__), "sheet_rules.json"))
