"""Render the six isolation sheets of the importer set (C14) from our own filled templates.

Three field layouts follow public isolation procedures (a register, a scheme with a bleed table, a line
opening list); no real company names or logos. The gold lists in cases.yaml are written by hand from
the same entries, not derived from this file. s05 has a deliberately illegible tag (gold: null).

    python eval/importer_set/make_sheets.py      # writes s01.png .. s06.png and s06.pdf next to this file
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
W, H = 1240, 900

# rows: (seq, tag, position, type, lock); proving: (tag, proves)
SHEETS = {
    "s01": {"style": "register", "ref": "IR-2211", "equipment": "F-210", "area": "Gas line",
            "rows": [(1, "XV-201", "Closed", "Proved", "D-01"), (2, "XV-203", "Closed", "Proved", "D-02"),
                     (3, "BV-202", "Open", "", ""), (4, "XV-204", "Closed", "Proved", "D-03")],
            "vent": "VV-213", "proving": [("BV-202", "XV-201, XV-203"), ("VV-213", "XV-204")], "hold": "10 min"},
    "s02": {"style": "scheme", "ref": "IS-0907", "equipment": "reactor", "area": "Reactor unit",
            "rows": [(1, "f1", "Closed", "NP", "31"), (2, "f2", "Closed", "NP", "32"), (3, "product", "Closed", "NP", "33")],
            "vent": "purge", "proving": [], "hold": "10 min"},
    "s03": {"style": "opening", "ref": "LO-5530", "equipment": "C-202", "area": "Gas line",
            "rows": [(1, "XV-201", "CLOSE", "Proved", "E-1"), (2, "XV-203", "CLOSE", "Proved", "E-2"),
                     (3, "BV-202", "OPEN", "", "")],
            "vent": "BV-202", "proving": [("BV-202", "XV-201, XV-203")], "hold": "10 min"},
    "s04": {"style": "register", "ref": "IR-2240", "equipment": "reactor", "area": "Reactor unit",
            "rows": [(1, "product", "Closed", "Non-proved", "L-41"), (2, "f1", "Closed", "Non-proved", "L-42"),
                     (3, "f2", "Closed", "Non-proved", "L-43")],
            "vent": "purge", "proving": [], "hold": "10 min"},
    "s05": {"style": "scheme", "ref": "IS-0931", "equipment": "F-210", "area": "Gas line", "rotate": 1.5,
            "rows": [(1, "XV-201", "Closed", "PR", "F-1"), (2, "XV-203", "Closed", "PR", "F-2"),
                     (3, "BV-202", "Open", "", ""), (4, "XV-204", "Closed", "PR", "F-3")],
            "smudge": {3}, "vent": "VV-213", "proving": [("BV-202", "XV-201, XV-203")], "hold": "10 min"},
    "s06": {"style": "opening", "ref": "LO-5561", "equipment": "L-230", "area": "Gas line", "pdf": True,
            "rows": [(1, "XV-204", "CLOSE", "Proved", "G-1"), (2, "XV-231", "CLOSE", "Non-proved", "G-2")],
            "vent": "none", "proving": [], "hold": "10 min"},
}

LAYOUT = {  # title, header labels, column headings, column x positions, legend
    "register": ("ISOLATION REGISTER", ("Register no.", "Equipment to be worked on", "Plant area"),
                 ("Seq", "Isolation point", "Isolated position", "Isolation method", "Lock no."),
                 (60, 160, 420, 660, 940), None),
    "scheme": ("ISOLATION SCHEME", ("Scheme ref", "Equipment", "Area"),
               ("Item", "Tag No.", "Position required", "Type", "Padlock"),
               (60, 160, 420, 700, 900), "Type: P = positive, PR = proved, NP = non-proved"),
    "opening": ("LINE / EQUIPMENT OPENING - ISOLATION LIST", ("List no.", "Line / equipment", "Unit"),
                ("Step", "Valve", "Action", "Isolation category", "Lock #"),
                (60, 160, 420, 620, 940), None),
}


def render(sid: str, s: dict) -> Image.Image:
    font, big, small = (ImageFont.load_default(size=n) for n in (22, 30, 18))
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    title, labels, cols, xs, legend = LAYOUT[s["style"]]
    d.rectangle((30, 30, W - 30, H - 30), outline="black", width=3)
    d.text((60, 50), title, font=big, fill="black")
    for i, (label, value) in enumerate(zip(labels, (s["ref"], s["equipment"], s["area"]))):
        y = 110 + 40 * i
        d.text((60, y), f"{label}:", font=font, fill="black")
        d.text((420, y), value, font=font, fill=(20, 20, 120))  # filled-in entries in blue
        d.line((410, y + 28, 900, y + 28), fill="gray")
    top = 250
    d.rectangle((50, top, W - 50, top + 44), fill=(225, 225, 225), outline="black")
    for x, c in zip(xs, cols):
        d.text((x, top + 10), c, font=font, fill="black")
    for r, row in enumerate(s["rows"]):
        y = top + 44 + 44 * r
        d.rectangle((50, y, W - 50, y + 44), outline="black")
        for x, v in zip(xs, row):
            d.text((x, y + 10), str(v), font=font, fill=(20, 20, 120))
        if r in s.get("smudge", ()):  # scribbled over: the tag can't be read
            x0 = xs[1] + 36
            d.ellipse((x0, y + 6, x0 + 52, y + 38), fill=(60, 60, 80))
            for k in range(6):
                d.line((x0 + 9 * k - 6, y + 4, x0 + 9 * k + 24, y + 40), fill=(40, 40, 70), width=4)
    y = top + 44 + 44 * len(s["rows"]) + 30
    if s["style"] == "scheme":
        d.text((60, y), "Bleed / vent points", font=font, fill="black")
        d.text((420, y), "Proves isolation of", font=font, fill="black")
        for i, (tag, proves) in enumerate(s["proving"] or [("-", "-")]):
            d.text((60, y + 34 * (i + 1)), tag, font=font, fill=(20, 20, 120))
            d.text((420, y + 34 * (i + 1)), proves, font=font, fill=(20, 20, 120))
        y += 34 * (max(1, len(s["proving"])) + 1) + 10
        d.text((60, y), f"Vent: {s['vent']}", font=font, fill=(20, 20, 120))
    else:
        d.text((60, y), f"Vent / drain point: {s['vent']}", font=font, fill=(20, 20, 120))
        for i, (tag, proves) in enumerate(s["proving"]):
            d.text((60, y + 34 * (i + 1)), f"Proving: {tag} proves {proves}", font=font, fill=(20, 20, 120))
        y += 34 * len(s["proving"])
    d.text((60, y + 44), f"Hold before sign-on: {s['hold']}", font=font, fill=(20, 20, 120))
    if legend:
        d.text((60, H - 120), legend, font=small, fill="black")
    for i, who in enumerate(("Prepared by", "Issued by", "Received by")):  # left blank: signing is a person's act
        d.text((60 + 380 * i, H - 80), f"{who}: ____________", font=small, fill="black")
    if s.get("rotate"):
        im = im.rotate(s["rotate"], resample=Image.BICUBIC, expand=False, fillcolor="white")
    return im


def main() -> None:
    for sid, s in SHEETS.items():
        im = render(sid, s).convert("L")  # grey keeps the files small
        im.save(HERE / f"{sid}.png", optimize=True)
        if s.get("pdf"):
            im.save(HERE / f"{sid}.pdf", resolution=150)
        print(sid, "written")


if __name__ == "__main__":
    main()
