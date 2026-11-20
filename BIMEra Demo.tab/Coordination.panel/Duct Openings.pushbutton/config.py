# -*- coding: utf-8 -*-
"""Shift+click: open the settings file (clearance, rounding, family) in Notepad."""
import os
os.startfile(os.path.join(os.path.dirname(__file__), "opening_settings.json"))
