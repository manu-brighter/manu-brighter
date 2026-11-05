#!/usr/bin/env python3
"""Render the profile's desktop and mobile SVGs from its local artwork and fonts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / ".build-deps").is_dir():
    sys.path.insert(0, str(ROOT / ".build-deps"))

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
BG, LIGHT, MUTED, CYAN, LINE = "#0d1117", "#e9f1f5", "#94a7b6", "#a0e8e8", "#27343f"


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") if value else "0"


def element(tag, **attrs):
    return ET.Element(f"{{{NS}}}{tag}", {key.replace("_", "-"): str(value) for key, value in attrs.items()})


class Typeface:
    def __init__(self, path, key):
        self.font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.metrics = self.font["hmtx"].metrics
        self.upm = self.font["head"].unitsPerEm
        self.key = key
        self.paths = {}

    def glyph(self, char):
        if ord(char) not in self.cmap:
            raise ValueError(f"Font {self.key} has no glyph for {char!r} (U+{ord(char):04X})")
        return self.cmap[ord(char)]

    def advance(self, char):
        return self.metrics[self.glyph(char)][0]

    def width(self, text, size, spacing=0):
        return sum(self.advance(char) for char in text) * size / self.upm + max(0, len(text) - 1) * spacing

    def path(self, char):
        if char not in self.paths:
            pen = SVGPathPen(self.glyphs)
            self.glyphs[self.glyph(char)].draw(pen)
            self.paths[char] = pen.getCommands()
        return self.paths[char]


class Canvas:
    def __init__(self, name, mobile, title, description, fonts, artwork):
        self.name, self.mobile, self.fonts, self.artwork = name, mobile, fonts, artwork
        self.width = 360 if mobile else 748
        self.pad = 22 if mobile else 35
        self.inner = self.width - 2 * self.pad
        self.root = element("svg", id="manual-mode", width=self.width, role="img", aria_labelledby=f"{name}-title {name}-desc")
        ET.SubElement(self.root, f"{{{NS}}}title", id=f"{name}-title").text = title
        ET.SubElement(self.root, f"{{{NS}}}desc", id=f"{name}-desc").text = description
        self.defs = ET.SubElement(self.root, f"{{{NS}}}defs")
        style = ET.SubElement(self.root, f"{{{NS}}}style")
        style.text = artwork["animationCss"]
        self.background = element("rect", width=self.width, fill=BG)
        self.root.append(self.background)
        self.defined_glyphs = set()
        self.copy = []
        self.text_bounds = []

    def add(self, tag, **attrs):
        node = element(tag, **attrs)
        self.root.append(node)
        return node

    def line(self, x1, y1, x2, y2, color=LINE):
        self.add("path", d=f"M{number(x1)} {number(y1)}H{number(x2)}" if y1 == y2 else f"M{number(x1)} {number(y1)}L{number(x2)} {number(y2)}", fill="none", stroke=color)

    def glyph_use(self, parent, char, font, x=0):
        key = f"mm-g-{font.key}-{ord(char):x}"
        if key not in self.defined_glyphs:
            self.defs.append(element("path", id=key, d=font.path(char)))
            self.defined_glyphs.add(key)
        parent.append(element("use", href=f"#{key}", x=number(x)))

    def text_group(self, text, x, y, size=14, fill=LIGHT, bold=False, spacing=0, anchor="start"):
        font = self.fonts[bool(bold)]
        width = font.width(text, size, spacing)
        if anchor == "middle":
            x -= width / 2
        elif anchor == "end":
            x -= width
        group = element("g", aria_label=text, role="img", fill=fill)
        scale = size / font.upm
        shape = element("g", transform=f"translate({number(x)} {number(y)}) scale({number(scale)} {number(-scale)})", aria_hidden="true")
        cursor = 0
        for char in text:
            self.glyph_use(shape, char, font, cursor)
            cursor += font.advance(char) + spacing / scale
        group.append(shape)
        return group, width

    def text(self, text, x, y, size=14, fill=LIGHT, bold=False, spacing=0, anchor="start"):
        group, width = self.text_group(text, x, y, size, fill, bold, spacing, anchor)
        self.root.append(group)
        self.copy.append(text)
        left = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
        self.text_bounds.append((text, left, y - size, left + width, y + size * .25))
        return width

    def wrap(self, text, width, size=14, bold=False, spacing=0):
        lines = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split():
                candidate = f"{current} {word}" if current else word
                if self.fonts[bool(bold)].width(candidate, size, spacing) > width:
                    if not current:
                        raise ValueError(f"Word does not fit in {width}px: {word}")
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        return lines

    def paragraph(self, text, x, y, width, size=14, leading=25, fill=MUTED, bold=False):
        for line in self.wrap(text, width, size, bold):
            self.text(line, x, y, size, fill, bold)
            y += leading
        return y

    def heading(self, title, subtitle=None):
        self.text(title, self.pad, 46, 23 if self.mobile else 25, bold=True, spacing=-.7)
        if subtitle:
            if self.mobile:
                self.text(subtitle, self.pad, 69, 12, MUTED)
            else:
                self.text(subtitle, self.width - self.pad, 46, 12, MUTED, anchor="end")

    def outline_art_text(self, root):
        paths = {node.get("id"): node.get("d") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "path" and node.get("id")}

        def visit(parent, inherited):
            current = dict(inherited)
            current.update({key: value for key, value in parent.attrib.items() if key in {"fill", "font-size", "font-weight", "text-anchor", "letter-spacing"}})
            for index, child in enumerate(list(parent)):
                if child.tag.rsplit("}", 1)[-1] != "text":
                    visit(child, current)
                    continue
                attrs = {**current, **child.attrib}
                label = "".join(child.itertext())
                size = float(attrs.get("font-size", 14))
                bold = attrs.get("font-weight", "400") in {"bold", "600", "700", "800", "900"}
                spacing = float(attrs.get("letter-spacing", 0))
                text_path = next((node for node in child if node.tag.rsplit("}", 1)[-1] == "textPath"), None)
                if text_path is not None:
                    replacement = self.arc_text(label, attrs, text_path, paths, size, bold, spacing)
                else:
                    replacement, _ = self.text_group(label, float(attrs.get("x", 0)), float(attrs.get("y", 0)), size, attrs.get("fill", LIGHT), bold, spacing, attrs.get("text-anchor", "start"))
                for key in ("class", "transform", "opacity", "clip-path"):
                    if child.get(key) is not None:
                        replacement.set(key, child.get(key))
                parent.remove(child)
                parent.insert(index, replacement)

        visit(root, {})

    def arc_text(self, label, attrs, text_path, paths, size, bold, spacing):
        """Outline the two circular camera engravings from their SVG arc geometry."""
        ref = text_path.get("href", text_path.get(f"{{http://www.w3.org/1999/xlink}}href", ""))
        path = paths[ref.lstrip("#")]
        values = [float(value) for value in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", path)]
        if len(values) != 9 or "a" not in path:
            raise ValueError(f"Unsupported engraving arc: {path}")
        x1, y1, rx, ry, rotation, large, sweep, dx, dy = values
        if rx != ry or rotation or large or dy:
            raise ValueError(f"Expected a horizontal circular engraving arc: {path}")
        cx = x1 + dx / 2
        cy = y1 + (1 if sweep else -1) * math.sqrt(max(0, rx * rx - dx * dx / 4))
        start = math.atan2(y1 - cy, x1 - cx)
        end = math.atan2(y1 + dy - cy, x1 + dx - cx)
        angle = (end - start) % (2 * math.pi) if sweep else -((start - end) % (2 * math.pi))
        length = abs(angle) * rx
        offset = text_path.get("startOffset", "0")
        cursor = length * float(offset[:-1]) / 100 if offset.endswith("%") else float(offset)
        font = self.fonts[bold]
        width = font.width(label, size, spacing)
        anchor = text_path.get("text-anchor", attrs.get("text-anchor", "start"))
        cursor -= width / 2 if anchor == "middle" else width if anchor == "end" else 0
        group = element("g", fill=attrs.get("fill", LIGHT), aria_label=label, role="img")
        scale = size / font.upm
        for char in label:
            advance = font.advance(char) * scale
            theta = start + angle * (cursor + advance / 2) / length
            x, y = cx + rx * math.cos(theta), cy + ry * math.sin(theta)
            tangent = math.degrees(theta) + (90 if sweep else -90)
            glyph = element("g", transform=f"translate({number(x)} {number(y)}) rotate({number(tangent)}) scale({number(scale)} {number(-scale)})", aria_hidden="true")
            self.glyph_use(glyph, char, font, -font.advance(char) / 2)
            group.append(glyph)
            cursor += advance + spacing
        return group

    def art(self, key, x, y, width, height):
        node = ET.fromstring(self.artwork[key])
        for child in node.iter():
            child.tag = f"{{{NS}}}{child.tag.rsplit('}', 1)[-1]}"
        node.set("x", number(x))
        node.set("y", number(y))
        node.set("width", number(width))
        node.set("height", number(height))
        node.set("preserveAspectRatio", "xMidYMid meet")
        self.outline_art_text(node)
        self.root.append(node)

    def save(self, height, output):
        self.root.set("height", number(height))
        self.root.set("viewBox", f"0 0 {self.width} {number(height)}")
        self.background.set("height", number(height))
        desc = self.root.find(f"{{{NS}}}desc")
        desc.text += " " + " ".join(self.copy)
        for text, left, top, right, bottom in self.text_bounds:
            if left < -1 or right > self.width + 1 or top < -1 or bottom > height + 1:
                raise ValueError(f"{self.name}: text outside canvas: {text!r}: {(left, top, right, bottom)}")
        ids = [node.get("id") for node in self.root.iter() if node.get("id")]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate IDs in {self.name}")
        for node in self.root.iter():
            if node.tag.rsplit("}", 1)[-1] in {"text", "textPath", "script", "foreignObject", "image"}:
                raise ValueError(f"Unexpected element in {self.name}: {node.tag}")
        filename = f"{self.name}{'-mobile' if self.mobile else ''}.svg"
        target = output / filename
        payload = ET.tostring(self.root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
        target.write_bytes(b"\n".join(line.rstrip() for line in payload.splitlines()) + b"\n")
        print(f"{target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}: {self.width}×{number(height)}, {target.stat().st_size:,} bytes")


def hero(c):
    p = c.pad
    c.text("mh,", p, 48 if c.mobile else 55, 20, CYAN, True, -.8)
    c.text("Basel region, Switzerland", c.width - p, 46 if c.mobile else 53, 12, MUTED, anchor="end")
    size, first, second = (62, 126, 190) if c.mobile else (77, 163, 241)
    c.text("Manuel", p, first, size, bold=True, spacing=-3 if c.mobile else -4)
    width = c.text("Heller", p, second, size, bold=True, spacing=-3 if c.mobile else -4)
    c.text(",", p + width - 1, second, size, CYAN, True)
    role = 231 if c.mobile else 302
    c.text("Full-stack developer.", p, role, 18, bold=True, spacing=-.3)
    c.text("PHP & Vue at zvoove.", p, role + 28, 14, CYAN)
    c.paragraph("Code, light, and things\nworth taking apart.", p, role + 55, c.inner if c.mobile else 260, leading=23)
    c.art("camera", -12 if c.mobile else 278, 302 if c.mobile else 80, 388 if c.mobile else 516, 303.125 if c.mobile else 403.125)
    note = 584 if c.mobile else 468
    c.line(p, note - 5, p + 25, note - 5, CYAN)
    c.text("Usually in manual mode.", p + 36, note, 14, MUTED)
    return 600 if c.mobile else 510


def club(c):
    c.heading("Made to be used.", "Personal projects, out in the world.")
    p, w = c.pad, c.inner
    panel = c.add("rect", x=p, y=88, width=w, rx=12, fill="#111b24", stroke=LINE)
    art_height = 150 if c.mobile else 208
    c.art("club", p, 89, w, art_height)
    divider = 89 + art_height
    c.line(p, divider, p + w, divider)
    x, y = p + (19 if c.mobile else 25), divider + 39
    c.text("Jogge di Balla", x, y, 22 if c.mobile else 23, bold=True, spacing=-.6)
    if c.mobile:
        y = c.paragraph("Co-founder & vice president.\nConcept, design, development, operation.", x, y + 30, w - 38, leading=23)
        y = c.paragraph("A club website grew into our everyday toolkit: memberships, events, orders connecting service, kitchen and bar, live photos and streaming overlays.", x, y + 17, w - 38)
    else:
        c.paragraph("Co-founder & vice president.\nConcept, design, development, operation.", x, y + 32, 275, leading=23)
        y = c.paragraph("A club website grew into our everyday toolkit: memberships, events, orders connecting service, kitchen and bar, live photos and streaming overlays.", p + 351, divider + 34, w - 376)
    panel.set("height", number(y - 88 + 6))
    return y + 26


PROJECTS = [
    ("shot", "One tap. Every screen.", "Shot-Counter connects phones and a shared scoreboard. QR joining, live sync and a desktop app.", "Vue 3 / Express / SQLite / Electron"),
    ("toolkit", "A workflow, packaged.", "Claude Code Kit: reusable skills and specialist agents for project upkeep, creative frontends and security reviews.", "Custom skills / Agents / AI workflows"),
]


def projects(c):
    w = c.inner if c.mobile else (c.inner - 22) / 2
    bottom, y = 0, 12
    for index, (art, title, copy, tech) in enumerate(PROJECTS):
        x = c.pad if c.mobile else c.pad + index * (w + 22)
        c.art(art, x, y, w, 150)
        c.line(x, y + 154, x + w, y + 154)
        c.text(title, x, y + 188, 19, bold=True, spacing=-.5)
        end = c.paragraph(copy, x, y + 218, w)
        end = c.paragraph(tech, x, end + 12, w, leading=23, fill="#91a8b8")
        bottom = max(bottom, end)
        if c.mobile:
            y = end + 20
    return bottom + 25


def portfolio(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    x = c.pad + (67 if c.mobile else 94)
    width = c.width - c.pad - x
    c.art("portfolio", c.pad, 28, 50 if c.mobile else 72, 80)
    y = c.paragraph("A website with a little fluid dynamics.", x, 43, width, 18, 25, LIGHT, True)
    y = c.paragraph("My portfolio brings photography and design together with a real GPU fluid simulation, four languages and device-aware quality.", x, y + 9, width)
    c.line(c.pad, y + 8, c.width - c.pad, y + 8)
    return y + 24


SKILLS = [
    ("At work", "PHP · Vue · MySQL", "Business interfaces, APIs and data synchronisation. Application development at zvoove since 2021."),
    ("Making sure it works", "Cypress · E2E testing", "Around 30 substantial release tests, execution and failure analysis. Playwright migration in progress."),
    ("My own products", "React · TypeScript · tRPC", "Built with AI support. I own the ideas, design and ongoing operation, alongside my PHP/Vue background."),
    ("Keeping them running", "Linux · nginx · Docker", "My rented root server, my configurations. Codex, Claude Code and custom skills in the daily workflow."),
]


def stack(c):
    c.heading("The tools behind it.", "At work, at home, behind the scenes.")
    w = c.inner if c.mobile else (c.inner - 30) / 2
    y, bottom, row_bottom = 107 if c.mobile else 100, 0, 0
    for index, (title, tech, copy) in enumerate(SKILLS):
        x = c.pad if c.mobile else c.pad + index % 2 * (w + 30)
        c.text(title, x, y, 14, "#d0dce5")
        c.text(tech, x, y + 29, 15, CYAN)
        end = c.paragraph(copy, x, y + 59, w)
        row_bottom, bottom = max(row_bottom, end), max(bottom, end)
        if c.mobile or index % 2:
            y = row_bottom + 27
            row_bottom = 0
    return bottom + 20


EXPERIMENTS = [
    ("Research concluded", "Mercurius", "Three trading hypotheses. None passed the backtests. No real money used; the results remain public."),
    ("Work in progress", "Fly connectome simulation", "An experiment with a fruit-fly neural wiring graph. The simulation runs; learning results are still ahead."),
]


def experiments(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    w = c.inner if c.mobile else (c.inner - 26) / 2
    y, bottom = 37, 0
    for index, (state, title, copy) in enumerate(EXPERIMENTS):
        x = c.pad if c.mobile else c.pad + index * (w + 26)
        c.add("circle", cx=x + 3, cy=y - 4, r=2.5, fill="#8c9ed8")
        c.text(state, x + 15, y, 12, MUTED)
        c.text(title, x, y + 31, 17, bold=True, spacing=-.35)
        end = c.paragraph(copy, x, y + 61, w)
        bottom = max(bottom, end)
        if c.mobile:
            y = end + 34
    return bottom + 25


def garage(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.heading("After the last commit.")
    art_height = c.inner * 205 / 650
    c.art("car", c.pad, 61, c.inner, art_height)
    y = 61 + art_height + 32
    w = c.inner if c.mobile else (c.inner - 26) / 2
    bottom = 0
    sections = [
        ("A different kind of manual.", "Wildlife, car photography and the occasional trip for a frame worth keeping. Sony α7 IV, Lightroom, Photoshop and DaVinci Resolve."),
        ("Still taking things apart.", "The Audi S5 project. Design experiments. Events with the club. Different interests, the same need to understand how things work."),
    ]
    for index, (title, copy) in enumerate(sections):
        x = c.pad if c.mobile else c.pad + index * (w + 26)
        c.text(title, x, y, 15, bold=True)
        end = c.paragraph(copy, x, y + 29, w)
        bottom = max(bottom, end)
        if c.mobile:
            y = end + 27
    return bottom + 20


EVENTS = [
    ("2016–20", "Novartis", "IT apprenticeship", "Betriebsinformatiker EFZ"),
    ("2021", "zvoove", "PHP, Vue", "and integrations"),
    ("2022", "Jogge di Balla", "Co-founder", "& vice president"),
    ("2023", "A camera joins in", "Wildlife, cars", "and better light"),
    ("2026", "Built & operated", "Club platform,", "apps and tools"),
]


def history(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.heading("Life, versioned.")
    # A vertical timeline keeps every event legible at the same 14px body size.
    y = 93
    if c.mobile:
        c.line(c.pad + 3, y - 5, c.pad + 3, y + 4 * 111 - 5, "#3b5362")
        for date, title, line1, line2 in EVENTS:
            c.add("circle", cx=c.pad + 3, cy=y - 5, r=3, fill=CYAN)
            x = c.pad + 24
            c.text(date, x, y, 14, CYAN)
            c.text(title, x, y + 26, 16, bold=True)
            c.paragraph(f"{line1}\n{line2}", x, y + 51, c.inner - 24, leading=22)
            y += 111
        return y - 13
    c.line(c.pad + 77, y - 5, c.pad + 77, y + 4 * 79 - 5, "#3b5362")
    for date, title, line1, line2 in EVENTS:
        c.text(date, c.pad, y, 14, CYAN)
        c.add("circle", cx=c.pad + 77, cy=y - 5, r=3, fill=CYAN)
        c.text(title, c.pad + 100, y, 16, bold=True)
        c.text(f"{line1} · {line2}", c.pad + 100, y + 26, 14, MUTED)
        y += 79
    return y - 17


def footer(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    w = c.text("manuel heller", c.pad, 47, 22, bold=True, spacing=-1)
    c.text(",", c.pad + w, 47, 22, CYAN, True)
    if c.mobile:
        c.text("Always something in development.", c.pad, 77, 14, MUTED)
        return 105
    c.text("Always something in development.", c.width - c.pad, 46, 14, MUTED, anchor="end")
    return 80


SECTIONS = [
    ("hero", "Manuel Heller, full-stack developer", "A detailed animated camera accompanies Manuel's introduction.", hero),
    ("club", "Jogge di Balla", "A service order travels to a kitchen screen and receipt printer.", club),
    ("projects", "Personal software projects", "Shot-Counter synchronises devices; Claude Code Kit checks a code change.", projects),
    ("portfolio", "Portfolio and photography", "Animated light lines reference the portfolio's GPU fluid simulation.", portfolio),
    ("stack", "Tools and experience", "Four areas of Manuel's daily development work.", stack),
    ("experiments", "Research and experiments", "Two public research projects, with their current status.", experiments),
    ("garage", "Outside the editor", "A silver-blue coupe, photography and hands-on interests.", garage),
    ("history", "Life, versioned", "Five milestones in work, personal projects and photography.", history),
    ("footer", "Manuel Heller", "Always something in development.", footer),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "manual-mode")
    args = parser.parse_args()
    artwork = json.loads((ROOT / "design" / "manual-mode-art.json").read_text(encoding="utf-8-sig"))
    fonts = {
        False: Typeface(ROOT / "design" / "fonts" / "manrope-regular.ttf", "regular"),
        True: Typeface(ROOT / "design" / "fonts" / "manrope-bold.ttf", "bold"),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name, title, description, render in SECTIONS:
        for mobile in (False, True):
            canvas = Canvas(name, mobile, title, description, fonts, artwork)
            canvas.save(render(canvas), args.output)


if __name__ == "__main__":
    main()
