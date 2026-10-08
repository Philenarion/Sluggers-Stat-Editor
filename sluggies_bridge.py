"""Bridge Mode: the editor started by Sluggies Tools on a modded game.

Sluggies Tools (a Mario Super Sluggers modding toolchain) can add character
IDs (0x66 and up) and moves the per-character stat tables to make room for
them, so the editor's vanilla tables and Gecko addresses no longer fit such a
game. Before Sluggies Tools starts the editor it writes ``stat_bridge.json``
into the editor's ``Bridge`` folder (``bridge_folder``: next to the exe, or
next to ``editor.py`` when it runs from source). With that file present the
editor runs in Bridge Mode:

* the characters are the bridge's (stock 0x00-0x64 first, in ID order, then
  the new IDs), grouped in the dropdowns by the square they share;
* the current values are read from the modded ``main.dol`` the bridge names;
  the defaults (what Reset goes back to) are the roster's values before any
  stat edit, from the bridge's baseline, else the editor's own vanilla lists;
* the Gecko Code tab becomes the Sluggies tab: **Send to Sluggies** writes
  ``stat_edits.json`` (every value that differs from what the editor opened
  with), deletes ``stat_bridge.json`` (one bridge, one session) and closes
  the editor. Sluggies Tools writes the game files itself and removes both
  files afterwards;
* Load changes still reads a Standalone save (``Save Files/*.txt``, V4 or
  V3) for the stock characters and the global tables, through the editor's
  own loader; only the saved values that differ from vanilla are kept
  (``merge_save``). Saving is hidden: the format has no room for new IDs.

Without the file nothing changes (Standalone). A bridge this module cannot use
(other format version, a ``main.dol`` that changed since the bridge was
written, ...) is reported once and the editor starts Standalone.

Chemistry: the game keeps one byte for a stock x new pair (in the new ID's
stats row), so such a pair is always edited in both directions. Stock x stock
and new x new pairs stay directional.

``editor.py`` calls ``load()`` before it builds the window (the lists the
widgets are made from must be in place by then) and ``finish()`` just before
``mainloop()``. Only the standard library is used.
"""

import base64
import copy
import hashlib
import json
import os
import struct
import sys
import tkinter as tk
from tkinter import messagebox

FOLDER = "Bridge"
BRIDGE_FILE = "stat_bridge.json"
EDITS_FILE = "stat_edits.json"
FORMAT = "sluggies-stat-bridge"
VERSION = 1
EDITS_FORMAT = "sluggies-stat-edits"
EDITS_VERSION = 1
TITLE = "Sluggies Bridge Mode"

STOCK = 101                   # stock IDs 0x00-0x64: the editor's own characters
CHEM_BASE = 0x28              # stats row: chemistry towards stock ID k at +0x28+k
STATS_U16 = set(range(10, 18)) | set(range(22, 26))
CHARACTER_TABLES = ("stats", "pitchwindup", "starpitch", "stamina", "changeup", "traj", "catchrange", "hitbox",
                    "sizescale")


def _stat_offset(j):
    """Stats row offset of editor stat j (0-25): the editor's getStatOffset(j) - 1."""
    if j < 11:
        return j + 2
    if j < 19:
        return 2 * j - 8
    if j < 23:
        return j + 10
    return 2 * j - 12


# (table, offset in the character's row, struct format) per entry of statsList / pitchingList / sizeList
STAT_FIELDS = ([("stats", _stat_offset(j), ">H" if j in STATS_U16 else ">B") for j in range(26)]
               + [("traj", 0, ">B"), ("traj", 1, ">B"), ("stamina", 0, ">H"), ("starpitch", 0, ">B")])
PITCHING_FIELDS = [("pitchwindup", 4 * j, ">f") for j in range(3)] + [("changeup", 4 * j, ">f") for j in range(2)]
SIZE_FIELDS = ([("sizescale", 4 * j, ">f") for j in range(2)] + [("catchrange", 4 * j, ">f") for j in range(10)]
               + [("hitbox", 4 * j, ">f") for j in range(2)])
# edit-file group, editor list of names, editor value lists (changed*/default*), field layout
CHARACTER_GROUPS = (("stats", "statsList", "Stat", STAT_FIELDS),
                    ("pitching", "pitchingList", "Pitching", PITCHING_FIELDS),
                    ("size", "sizeList", "Size", SIZE_FIELDS))
STAR_BOOST_LAYOUT = ((0, ">I"), (4, ">f"), (8, ">h"), (10, ">h"))   # add/mult op, amount, min, max
STAR_BOOST_OPS = (1, 2)
RANGES = {">B": (0, 0xFF), ">H": (0, 0xFFFF), ">h": (-0x8000, 0x7FFF), ">I": (0, 0xFFFFFFFF)}
# editor value lists (changed*/default*) a Standalone save file (V4, or V3 for the first three) holds; the
# per-character ones cover the stock rows 0-100, chemistry stock x stock
SAVE_LISTS = ("Chem", "Stat", "Traj", "Size", "Pitching", "Speed", "StarsTeam", "StarBoost", "StarHandicap",
              "HandicapParams")

_session = None
_problem = None


class BridgeError(Exception):
    pass


def keys(names):
    """Edit-file keys for an editor list: the name, or name#index where the name repeats."""
    return [n if names.count(n) == 1 else "%s#%d" % (n, i) for i, n in enumerate(names)]


def numbered(count):
    return [str(i) for i in range(count)]


def hex_id(cid):
    return "0x%02X" % cid


def nice_float(raw):
    """A stored f32 as the shortest decimal that stores back to the same bytes (whole numbers as int, like the
    editor's own lists)."""
    value = struct.unpack(">f", raw)[0]
    if value != value or value in (float("inf"), float("-inf")):
        return value
    for digits in range(1, 10):
        short = float("%.*g" % (digits, value))
        if struct.pack(">f", short) == raw:
            value = short
            break
    return int(value) if value.is_integer() and abs(value) < 2 ** 31 else value


def unpack(fmt, raw):
    return nice_float(raw) if fmt == ">f" else struct.unpack(fmt, raw)[0]


def value_problem(fmt, value, choices=None):
    """Why value cannot be stored as fmt, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "%r is not a number" % (value,)
    if fmt == ">f":
        if value != value or abs(value) > 3.4028234663852886e38:
            return "%r does not fit a 32-bit float" % (value,)
        return None
    if not float(value).is_integer():
        return "%r is not a whole number" % (value,)
    if choices is not None and value not in choices:
        return "%r is not one of %s" % (value, ", ".join(map(str, choices)))
    low, high = RANGES[fmt]
    if not low <= value <= high:
        return "%r is outside %d-%d" % (value, low, high)
    return None


def _int(text, what):
    try:
        return int(text, 0) if isinstance(text, str) else int(text)
    except (TypeError, ValueError):
        raise BridgeError("%s: %r is not a number" % (what, text)) from None


class Session:
    """One Bridge Mode run: the bridge, the values the editor opened with, sending the edits."""

    def __init__(self, ns, folder, path):
        self.ns = ns
        self.folder = folder
        self.bridge_path = path
        self.sent = False
        try:
            with open(path, "rb") as f:
                raw = f.read()
            self.bridge_sha1 = hashlib.sha1(raw).hexdigest()
            bridge = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise BridgeError("%s cannot be read: %s" % (path, exc)) from None
        if not isinstance(bridge, dict) or bridge.get("format") != FORMAT:
            raise BridgeError("%s is not a Sluggies stat bridge." % path)
        if bridge.get("version") != VERSION:
            raise BridgeError("The bridge file is version %s; this editor understands version %d. "
                              "Update the editor or Sluggies Tools." % (bridge.get("version"), VERSION))
        self.bridge = bridge
        files = bridge.get("files") or {}
        self.dol_path = files.get("main_dol") or ""
        try:
            with open(self.dol_path, "rb") as f:
                self.dol = f.read()
        except OSError as exc:
            raise BridgeError("main.dol cannot be read (%s): %s" % (self.dol_path, exc)) from None
        self.sha1 = files.get("main_dol_sha1")
        if hashlib.sha1(self.dol).hexdigest() != self.sha1:
            raise BridgeError("%s changed after the bridge was written. Start the editor from Sluggies Tools again."
                              % self.dol_path)
        self.ids = self._characters(bridge.get("characters"))
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        self.tables = self._tables(bridge.get("tables"))
        self.matrix = self._new_by_new(bridge.get("chemistry"))
        self.globals = self._globals(bridge.get("globals"))
        self.baseline = self._baseline(bridge.get("baseline") or {})
        self._install()

    # -- reading the bridge --------------------------------------------------------------------------------------

    def _characters(self, characters):
        if not isinstance(characters, list) or len(characters) < STOCK:
            raise BridgeError("The bridge does not list the stock characters.")
        out = []
        self.bridge_names = []
        for i, c in enumerate(characters):
            cid = _int(c.get("id"), "character id")
            if i < STOCK and cid != i:
                raise BridgeError("The bridge lists the stock characters out of order (0x%02X at %d)." % (cid, i))
            if i >= STOCK and (cid <= out[-1] or cid > 0xFE):
                raise BridgeError("New character 0x%02X is out of order or out of range." % cid)
            out.append(cid)
            self.bridge_names.append((c.get("name"), _int(c.get("family", c.get("id")), "family")))
        return out

    def _span(self, offset, size, what):
        if not (isinstance(offset, int) and 0 <= offset and offset + size <= len(self.dol)):
            raise BridgeError("%s lies outside main.dol." % what)
        return offset

    def _tables(self, tables):
        out = {}
        for name in CHARACTER_TABLES:
            t = (tables or {}).get(name)
            if not t:
                raise BridgeError("The bridge has no '%s' table." % name)
            rows = _int(t.get("rows"), name)
            if self.ids[-1] >= rows:
                raise BridgeError("The '%s' table has %d rows, too few for 0x%02X." % (name, rows, self.ids[-1]))
            header, row_size = _int(t.get("header"), name), _int(t.get("row_size"), name)
            start = self._span(t.get("file_offset"), header + row_size * rows, "The '%s' table" % name)
            out[name] = (start + header, row_size)
        return out

    def _new_by_new(self, chemistry):
        if len(self.ids) == STOCK:
            return None
        m = (chemistry or {}).get("new_x_new")
        if not m:
            raise BridgeError("The bridge has new characters but no new x new chemistry matrix.")
        first, size = _int(m.get("first_id"), "first_id"), _int(m.get("size"), "size")
        if self.ids[STOCK] < first or self.ids[-1] >= first + size:
            raise BridgeError("The new x new chemistry matrix does not cover every new character.")
        start = self._span(m.get("file_offset"), size * size, "The new x new chemistry matrix")
        return start, first, size

    def _globals(self, places):
        """file offset per editor global list and cell: name -> function(i, j) -> (offset, format)."""
        places = places or {}
        try:
            speed = places["speed"]
            base = {0: speed["Baserunning"]["file_offset"], 1: speed["Fielding"]["file_offset"]}
            traj = places["traj_heights"]["file_offset"]
            team = places["team_stars"]["file_offset"]
            handicap = places["star_handicap"]["file_offset"]
            boost = places["star_boost"]["file_offset"]
            params = [[p["file_offset"] for p in row] for row in places["handicap_params"]]
        except (KeyError, TypeError, IndexError):
            raise BridgeError("The bridge does not place every global table.") from None
        events = len(self.ns["starEventsList"])
        out = {
            "Speed": lambda i, j: (base[j] + 4 * i, ">f"),
            "Traj": lambda i, j: (traj + 25 * i + j, ">B"),
            "StarsTeam": lambda i, j: (team + 2 * events * i + 2 * j, ">h"),
            "StarHandicap": lambda i, j: (handicap + 8 * i + 4 * j, ">f"),
            "StarBoost": lambda i, j: (boost + 12 * i + STAR_BOOST_LAYOUT[j][0], STAR_BOOST_LAYOUT[j][1]),
            "HandicapParams": lambda i, j: (params[i][j], ">B"),
        }
        for name, place in out.items():
            for i, row in enumerate(self.ns["default" + name]):
                for j in range(len(row)):
                    offset, fmt = place(i, j)
                    self._span(offset, struct.calcsize(fmt), "Global table %s" % name)
        return out

    def _baseline(self, baseline):
        rows = {}
        try:
            for name in CHARACTER_TABLES:
                for key, text in (baseline.get(name) or {}).items():
                    rows[(name, _int(key, name))] = base64.b64decode(text)
            matrix = base64.b64decode(baseline["new_x_new"]) if baseline.get("new_x_new") else None
        except (TypeError, ValueError):
            raise BridgeError("The bridge's baseline cannot be decoded.") from None
        for cid in self.ids[STOCK:]:
            missing = [name for name in CHARACTER_TABLES if (name, cid) not in rows]
            if missing:
                raise BridgeError("The bridge has no baseline for 0x%02X (%s)." % (cid, ", ".join(missing)))
        if self.matrix is not None and (matrix is None or len(matrix) != self.matrix[2] ** 2):
            raise BridgeError("The bridge's new x new chemistry baseline is missing or the wrong size.")
        return rows, matrix

    # -- values ----------------------------------------------------------------------------------------------------

    def _dol_row(self, table, cid):
        start, size = self.tables[table]
        return self.dol[start + size * cid:start + size * (cid + 1)]

    def _base_row(self, table, cid):
        return self.baseline[0].get((table, cid))

    def _character_values(self, row_of, layout, vanilla):
        """An editor per-character list (one row per character) from row_of(table, cid); a stock row that
        row_of does not have comes from the editor's vanilla list."""
        out = []
        for cid in self.ids:
            values = []
            for j, (table, offset, fmt) in enumerate(layout):
                row = row_of(table, cid)
                if row is None:
                    values.append(vanilla[cid][j])
                else:
                    values.append(unpack(fmt, row[offset:offset + struct.calcsize(fmt)]))
            out.append(values)
        return out

    def _chemistry(self, row_of, matrix, vanilla):
        n = len(self.ids)
        out = [[0] * n for _ in range(n)]
        for i, a in enumerate(self.ids):
            for j, b in enumerate(self.ids):
                if a < STOCK and b < STOCK:
                    row = row_of("stats", a)
                    out[i][j] = vanilla[a][b] if row is None else row[CHEM_BASE + b]
                elif a < STOCK or b < STOCK:
                    new, stock = (a, b) if b < STOCK else (b, a)
                    out[i][j] = row_of("stats", new)[CHEM_BASE + stock]
                else:
                    first, size = self.matrix[1], self.matrix[2]
                    out[i][j] = matrix[(a - first) * size + (b - first)]
        return out

    def _dol_globals(self):
        out = {}
        for name, place in self.globals.items():
            rows = []
            for i, row in enumerate(self.ns["default" + name]):
                cells = []
                for j in range(len(row)):
                    offset, fmt = place(i, j)
                    cells.append(unpack(fmt, self.dol[offset:offset + struct.calcsize(fmt)]))
                rows.append(cells)
            out[name] = rows
        return out

    def _names(self):
        """Unique display names (the editor finds characters by name)."""
        vanilla = self.ns["charList"]
        names = []
        for i, (name, _family) in enumerate(self.bridge_names):
            name = " ".join(str(name).split()) if name else ""
            names.append(name or (vanilla[i] if i < STOCK else "Character " + hex_id(self.ids[i])))
        for i, name in enumerate(names):
            if names.count(name) > 1:
                names[i] = "%s (%s)" % (name, hex_id(self.ids[i]))
        return names

    def _combo(self, names):
        """comboList: families (characters of one square) as a header plus indented members, alphabetical."""
        families = {}
        for i, (_name, family) in enumerate(self.bridge_names):
            families.setdefault(family if family in self.index else self.ids[i], []).append(i)
        taken = set(names)
        entries = []
        for family, members in families.items():
            head = names[self.index[family]]
            members = sorted(members, key=lambda i: names[i].lower())
            if len(members) == 1:
                entries.append((head.lower(), [names[members[0]]]))
                continue
            header = head + " group"
            while header in taken:
                header += "+"
            taken.add(header)
            entries.append((head.lower(), [header] + ["  " + names[i] for i in members]))
        combo, sizes = [], []
        for _key, group in sorted(entries, key=lambda e: e[0]):
            combo.extend(group)
            sizes.extend([len(group) - 1] + [1] * (len(group) - 1) if len(group) > 1 else [1])
        return combo, sizes

    def _install(self):
        ns = self.ns
        names = self._names()
        combo, sizes = self._combo(names)
        matrix = self.baseline[1]
        self.vanilla = {name: copy.deepcopy(ns["default" + name]) for name in SAVE_LISTS}   # for load_save
        current = {}
        for _group, _list, name, layout in CHARACTER_GROUPS:
            vanilla = ns["default" + name]
            ns["default" + name] = self._character_values(self._base_row, layout, vanilla)
            current[name] = self._character_values(self._dol_row, layout, vanilla)
        if self.matrix is not None:
            start, _first, size = self.matrix
            dol_matrix = self.dol[start:start + size * size]
        else:
            dol_matrix = None
        vanilla_chem = ns["defaultChem"]
        ns["defaultChem"] = self._chemistry(self._base_row, matrix, vanilla_chem)
        current["Chem"] = self._chemistry(self._dol_row, dol_matrix, vanilla_chem)
        current.update(self._dol_globals())
        self.initial = copy.deepcopy(current)
        for name, values in current.items():
            ns["changed" + name] = values
        ns["charList"] = names
        ns["comboList"] = combo
        ns["getGroupSize"] = lambda n: sizes[n]
        self.combo_entry = {entry.strip(): entry for entry, size in zip(combo, sizes)}

    # -- the editor's edits ----------------------------------------------------------------------------------------

    def collect(self):
        """(edit file dict, number of values, problems) for everything that differs from what the editor opened
        with."""
        ns = self.ns
        characters, problems, count = {}, [], 0
        names = ns["charList"]

        def put(cid, group, key, value, fmt, choices=None):
            nonlocal count
            if isinstance(value, float) and fmt != ">f" and value.is_integer():
                value = int(value)
            problem = value_problem(fmt, value, choices)
            if problem:
                problems.append("%s, %s: %s" % (names[self.index[cid]], key, problem))
            characters.setdefault(hex_id(cid), {}).setdefault(group, {})[key] = value
            count += 1

        for group, list_name, name, layout in CHARACTER_GROUPS:
            field_keys = keys(ns[list_name])
            changed, initial = ns["changed" + name], self.initial[name]
            for i, cid in enumerate(self.ids):
                for j, (_table, _offset, fmt) in enumerate(layout):
                    if changed[i][j] != initial[i][j]:
                        put(cid, group, field_keys[j], changed[i][j], fmt)

        changed, initial = ns["changedChem"], self.initial["Chem"]
        for i, a in enumerate(self.ids):
            for j, b in enumerate(self.ids):
                if (a < STOCK) == (b < STOCK):      # stock x stock, new x new: directional
                    if changed[i][j] != initial[i][j]:
                        put(a, "chemistry", hex_id(b), changed[i][j], ">B", (0, 1, 2))
                elif b < STOCK:                      # new a x stock b: one byte, in the new ID's row
                    value = changed[i][j] if changed[i][j] != initial[i][j] else changed[j][i]
                    if value != initial[i][j]:
                        put(a, "chemistry", hex_id(b), value, ">B", (0, 1, 2))

        global_edits = {}
        tables = (("speed", "Speed", numbered(len(ns["defaultSpeed"])), keys(ns["speedList"])),
                  ("traj_heights", "Traj", numbered(len(ns["defaultTraj"])), numbered(len(ns["defaultTraj"][0]))),
                  ("team_stars", "StarsTeam", keys(ns["teamList"]), keys(ns["starEventsList"])),
                  ("star_handicap", "StarHandicap", numbered(4), numbered(2)),
                  ("star_boost", "StarBoost", keys(ns["starBoostStatsList"]), keys(ns["starBoostList"])),
                  ("handicap_params", "HandicapParams", numbered(2), numbered(3)))
        for key, name, row_keys, column_keys in tables:
            changed, initial = ns["changed" + name], self.initial[name]
            for i, row in enumerate(initial):
                for j, before in enumerate(row):
                    value = changed[i][j]
                    if value == before:
                        continue
                    fmt = self.globals[name](i, j)[1]
                    if isinstance(value, float) and fmt != ">f" and value.is_integer():
                        value = int(value)
                    choices = STAR_BOOST_OPS if name == "StarBoost" and j == 0 else None
                    problem = value_problem(fmt, value, choices)
                    if problem:
                        problems.append("%s %s, %s: %s" % (key, row_keys[i], column_keys[j], problem))
                    global_edits.setdefault(key, {}).setdefault(row_keys[i], {})[column_keys[j]] = value
                    count += 1

        edits = {"format": EDITS_FORMAT, "version": EDITS_VERSION, "main_dol_sha1": self.sha1,
                 "characters": characters, "globals": global_edits}
        return edits, count, problems

    # -- Standalone save files -------------------------------------------------------------------------------------

    def snapshot(self):
        return {name: copy.deepcopy(self.ns["changed" + name]) for name in SAVE_LISTS}

    def merge_save(self, before):
        """After the editor's own loader filled changed* from a Standalone save: keep only the loaded values that
        differ from vanilla, and put the values from before back where the save just holds vanilla. A Standalone
        save stores every value, so loading it as it is would undo the roster's stats sources and the stat edits
        already in the game. Returns (values applied, vanilla values skipped)."""
        applied = skipped = 0
        for name in SAVE_LISTS:
            changed, vanilla, old = self.ns["changed" + name], self.vanilla[name], before[name]
            for i, row in enumerate(vanilla):
                for j, plain in enumerate(row):
                    if changed[i][j] == old[i][j]:
                        continue
                    if changed[i][j] == plain:
                        changed[i][j] = old[i][j]
                        skipped += 1
                    else:
                        applied += 1
        return applied, skipped

    def load_save(self):
        """The Load changes button in Bridge Mode: the editor's loader (V4, else V3), then merge_save."""
        ns = self.ns
        before = self.snapshot()
        ns["loadChanges"]()
        applied, skipped = self.merge_save(before)
        if not applied and not skipped:
            return              # nothing loaded (the editor's loader reported why) or nothing new in the save
        ns["changedTrajListUsed"]()     # the loader showed the unmerged values; show the merged ones
        ns["trajDisplay"](1)
        ns["starBoostDisplay"]()
        ns["estarHandicapDisplay"]()
        ns["estarDisplay"](1)
        ns["speedDisplay"]()
        ns["hitboxDisplay"](1)
        ns["chemColor"]()
        recap = ns["recapList"]
        recap.configure(state="normal")
        recap.insert(tk.END, "Bridge Mode: %d value%s from the save applied to stock characters and global tables; "
                             "%d vanilla value%s in the save left as the game has them\n"
                     % (applied, "" if applied == 1 else "s", skipped, "" if skipped == 1 else "s"))
        recap.configure(state="disabled")

    def _summary(self, edits, count):
        if not count:
            return "no changed values"
        chars = len(edits["characters"])
        glob = sum(len(cols) for rows in edits["globals"].values() for cols in rows.values())
        parts = ["%d changed value%s" % (count, "" if count == 1 else "s")]
        if chars:
            parts.append("%d character%s" % (chars, "" if chars == 1 else "s"))
        if glob:
            parts.append("%d global value%s" % (glob, "" if glob == 1 else "s"))
        return parts[0] + (" (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else "")

    def send(self):
        edits, count, problems = self.collect()
        root = self.ns["root"]
        if problems:
            shown = problems[:15] + (["... and %d more" % (len(problems) - 15)] if len(problems) > 15 else [])
            messagebox.showerror(TITLE, "These values cannot be stored in the game:\n\n" + "\n".join(shown),
                                 parent=root)
            return
        if not messagebox.askyesno(TITLE, "Send %s to Sluggies Tools and close the editor?\n\n"
                                   "Sluggies Tools stages them; Patch Game writes them into the game files."
                                   % self._summary(edits, count), parent=root):
            return
        path = os.path.join(self.folder, EDITS_FILE)
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(edits, f, ensure_ascii=False, indent=1)
            os.replace(path + ".tmp", path)
        except OSError as exc:
            messagebox.showerror(TITLE, "The edits could not be written to %s:\n%s" % (path, exc), parent=root)
            return
        self.sent = True
        self._delete_bridge()
        root.destroy()

    def _delete_bridge(self):
        """Delete the bridge file this session was opened from, and nothing else: only that one path in the Bridge
        folder, only a regular file, and only while it still holds the bytes this session read (a newer bridge
        stays). A failure is harmless: Sluggies Tools removes leftovers itself."""
        path = self.bridge_path
        if (os.path.normcase(os.path.abspath(path))
                != os.path.normcase(os.path.abspath(os.path.join(self.folder, BRIDGE_FILE)))):
            return
        if os.path.islink(path) or not os.path.isfile(path):
            return
        try:
            with open(path, "rb") as f:
                if hashlib.sha1(f.read()).hexdigest() != self.bridge_sha1:
                    return
            os.remove(path)
        except OSError:
            pass

    def close(self):
        root = self.ns["root"]
        if not self.sent:
            edits, count, _problems = self.collect()
            if count and not messagebox.askyesno(
                    TITLE, "Not sent to Sluggies Tools yet: %s.\nThey are lost if you close the editor now.\n\n"
                    "Close the editor anyway?" % self._summary(edits, count), parent=root):
                return
        root.destroy()

    # -- the window ------------------------------------------------------------------------------------------------

    def finish(self):
        ns = self.ns
        root = ns["root"]
        root.title(root.title() + " - Bridge Mode (Sluggies Tools)")
        for widget in ("geckoGenerateFrame", "geckoWarningFrame", "geckoPlayersFrame", "geckoCodeLoaderFrame",
                       "geckoDisplayFrame"):
            ns[widget].grid_remove()
        # save files: loading only (a Standalone save has room for the 101 stock characters alone)
        ns["geckoSave"].pack_forget()
        ns["geckoSecurity"].pack_forget()
        ns["geckoLoad"].configure(command=self.load_save)
        ns["geckoFileFrame"].configure(text="Load a Standalone save (file name can't contain spaces or special "
                                            "characters)")
        tabs, gecko = ns["statsTabs"], ns["geckoFrame"]
        tabs.tab(gecko, text="Sluggies")
        new = len(self.ids) - STOCK
        frame = tk.LabelFrame(gecko, text="Sluggies Tools")
        frame.grid(row=0, column=0, columnspan=4, padx=5, pady=5, sticky=tk.EW)
        tk.Label(frame, justify=tk.LEFT, wraplength=560, text=(
            "Bridge Mode: the values come from\n%s\n(%d characters, %d of them new).\n\n"
            "Send to Sluggies hands every value you changed to Sluggies Tools and closes the editor. "
            "Sluggies Tools writes them into the game with Patch Game. Gecko codes, saving and the "
            "Gecko code loader are not available in Bridge Mode.\n\n"
            "Load changes reads a Standalone save (V4 or V3) for the stock characters and the global tables. "
            "Only values that differ from vanilla are taken; everything else keeps the game's current value."
            % (self.dol_path, len(self.ids), new))
        ).pack(padx=5, pady=5, anchor=tk.W)
        tk.Button(frame, text="Send to Sluggies", command=self.send, width=20).pack(pady=(0, 8))
        root.protocol("WM_DELETE_WINDOW", self.close)
        recap = ns["recapList"]
        recap.configure(state="normal")
        recap.insert(tk.END, "Bridge Mode: %d characters (%d new) from Sluggies Tools\n" % (len(self.ids), new))
        recap.configure(state="disabled")
        focus = self.bridge.get("focus")
        if focus is not None:
            self._focus(_int(focus, "focus"))

    def _focus(self, cid):
        ns = self.ns
        if cid not in self.index:
            return
        entry = self.combo_entry.get(ns["charList"][self.index[cid]])
        if entry is None:
            return
        ns["cbStatPlayer"].set(entry)
        ns["statDisplay"](0)
        ns["cbHitboxPlayer"].set(entry)
        ns["hitboxDisplay"](0)
        ns["chemFrom"].set(entry)
        ns["chemColor"]()
        ns["statsTabs"].select(ns["manualStatsFrame"])

    @staticmethod
    def symmetric(a, b):
        """True when the game stores one value for chemistry a <-> b (a stock x new pair)."""
        return (a < STOCK) != (b < STOCK)


def bridge_folder(editor_file):
    """The editor's Bridge folder: next to the exe (a PyInstaller build keeps editor.py inside _internal), else
    next to editor.py."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), FOLDER)
    return os.path.join(os.path.dirname(os.path.abspath(editor_file)), FOLDER)


def load(ns, editor_file):
    """Bridge Mode when Bridge/stat_bridge.json exists: replaces the editor's character lists, values and
    defaults in ns (editor.py's globals) and returns the session; None (Standalone) otherwise."""
    global _session, _problem
    folder = bridge_folder(editor_file)
    path = os.path.join(folder, BRIDGE_FILE)
    if not os.path.isfile(path):
        return None
    try:
        _session = Session(ns, folder, path)
    except BridgeError as exc:
        _problem = str(exc)
        return None
    return _session


def finish(ns):
    """After the window is built: the Sluggies tab, the close check, or the reason Bridge Mode was refused."""
    if _session is not None:
        _session.finish()
    elif _problem is not None:
        messagebox.showwarning(TITLE, _problem + "\n\nThe editor starts in Standalone mode.", parent=ns["root"])
