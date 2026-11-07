#!/usr/bin/env python3
"""Render the profile's desktop and mobile SVGs from its local artwork and fonts."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from functools import partial
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
BG, LIGHT, MUTED, CYAN, LINE = "#0d1117", "#f1edf8", "#aaa3bc", "#acbfff", "#302c42"
ACCENT, VIOLET = "#dcff6b", "#9b78ff"


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
    def __init__(self, name, mobile, title, description, fonts, artwork, columns=1, width=None):
        self.name, self.mobile, self.fonts, self.artwork = name, mobile, fonts, artwork
        self.width = width if width is not None else (360 if mobile else 748)
        if columns > 1:
            self.width /= columns
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
        ids = {child.get("id"): f"{self.name}-{key}-{child.get('id')}" for child in node.iter() if child.get("id")}
        for child in node.iter():
            child.tag = f"{{{NS}}}{child.tag.rsplit('}', 1)[-1]}"
            if child.get("id"):
                child.set("id", ids[child.get("id")])
            for attribute, value in list(child.attrib.items()):
                if attribute.rsplit("}", 1)[-1] == "href" and value.startswith("#"):
                    child.set(attribute, "#" + ids[value[1:]])
                elif attribute in {"aria-labelledby", "aria-describedby"}:
                    child.set(attribute, " ".join(ids.get(part, part) for part in value.split()))
                else:
                    child.set(attribute, re.sub(r"url\(#([^)]+)\)", lambda match: f"url(#{ids[match[1]]})", value))
            if child.tag == f"{{{NS}}}style" and child.text:
                child.text = re.sub(r"url\(#([^)]+)\)", lambda match: f"url(#{ids[match[1]]})", child.text)
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
    glow = element("radialGradient", id="mm-violet-light", cx=".5", cy=".5", r=".5")
    glow.append(element("stop", stop_color="#7951ee", stop_opacity=".38"))
    glow.append(element("stop", offset="1", stop_color="#7951ee", stop_opacity="0"))
    c.defs.append(glow)
    light = element("linearGradient", id="mm-light-trace", x1="0", y1="1", x2="1", y2="0")
    for offset, color, opacity in [("0", VIOLET, ".08"), (".3", VIOLET, ".9"), (".67", "#c8a6ff", ".8"), ("1", ACCENT, ".12")]:
        light.append(element("stop", offset=offset, stop_color=color, stop_opacity=opacity))
    c.defs.append(light)
    c.add("ellipse", cx=235 if c.mobile else 570, cy=450 if c.mobile else 302, rx=270 if c.mobile else 350, ry=215, fill="url(#mm-violet-light)")
    trace = "M-25 557C108 537 47 350 221 342S401 455 351 504" if c.mobile else "M210 488C374 443 292 100 574 118S866 371 646 453"
    c.add("path", d=trace, fill="none", stroke="url(#mm-light-trace)", stroke_width="20", opacity=".055")
    c.add("path", d=trace, fill="none", stroke="url(#mm-light-trace)", stroke_width="4", opacity=".32")
    c.add("path", d=trace, fill="none", stroke="url(#mm-light-trace)", stroke_width="1.1", opacity=".85")
    c.text("Basel region, Switzerland", c.width - p, 46 if c.mobile else 53, 12, MUTED, anchor="end")
    size, first, second = (62, 126, 190) if c.mobile else (77, 163, 241)
    c.text("Manuel", p, first, size, fill=ACCENT, bold=True, spacing=-3 if c.mobile else -4)
    width = c.text("Heller", p, second, size, fill=ACCENT, bold=True, spacing=-3 if c.mobile else -4)
    c.text(",", p + width - 1, second, size, ACCENT, True)
    role = 231 if c.mobile else 302
    c.text("Full-stack developer.", p, role, 18, bold=True, spacing=-.3)
    c.text("Code, design & photography.", p, role + 28, 14, ACCENT)
    c.paragraph("From club software\nto connectome experiments.", p, role + 55, c.inner if c.mobile else 260, leading=23)
    c.art("camera", -12 if c.mobile else 278, 302 if c.mobile else 80, 388 if c.mobile else 516, 303.125 if c.mobile else 403.125)
    note = 584 if c.mobile else 468
    c.line(p, note - 5, p + 25, note - 5, ACCENT)
    c.text("Usually in manual mode.", p + 36, note, 14, MUTED)
    return 600 if c.mobile else 510


def intro(c):
    end = c.paragraph(
        "I build web apps, APIs and tools, from club software to experiments. "
        "Beyond code: design, photography, video and a lowered S5.",
        c.pad, 19, c.inner, 14, 24,
    )
    return end + 8


NAV_LINKS = [
    ("nav-portfolio", "Portfolio", 0, ACCENT),
    ("nav-photography", "Photography", 1, ACCENT),
    ("nav-club", "Jogge di Balla", 2, ACCENT),
    ("nav-skills", "Skills", 0, CYAN),
    ("nav-projects", "All projects", 1, CYAN),
    ("nav-activity", "GitHub activity", 2, CYAN),
]


def link_label(c, label, position=0, color=ACCENT, compact=False):
    size = 13 if compact and c.mobile else 14
    anchor = ("start", "middle", "end")[position]
    x = (c.pad, c.width / 2, c.width - c.pad)[position]
    width = c.text(label, x, 23, size, color, anchor=anchor)
    left = x - (width if position == 2 else width / 2 if position == 1 else 0)
    c.line(left, 29, left + width, 29, color)
    return 48


DISCLOSURES = [
    ("disclosure-club", "Inside Jogge di Balla", "From service to kitchen and bar"),
]


def disclosure(c, label, subtitle=None):
    # The native summary marker supplies the first part of the content inset.
    x = 4 if c.mobile else 16
    c.text(label, x, 21 if subtitle else 32, 14, ACCENT, True)
    if subtitle:
        c.text(subtitle, x, 42, 12, MUTED)
    return 54


def activity(c):
    data = c.activity
    start, finish = date.fromisoformat(data["from"]), date.fromisoformat(data["to"])
    months = data["months"]
    day_count = (finish - start).days + 1
    expected = [(start + timedelta(days=i)).isoformat() for i in range(day_count)]
    last_month = finish.year * 12 + finish.month - 1
    expected_months = [f"{value // 12:04d}-{value % 12 + 1:02d}" for value in range(last_month - 11, last_month + 1)]
    if data["schema_version"] != 2 or data["days"] != day_count or months != expected_months or start.isoformat() != months[0] + "-01" or len(data["repositories"]) != 4:
        raise ValueError("Activity must contain four projects and twelve consecutive calendar months")
    labels = {
        "joggediballa-mainpage": "Jogge di Balla",
        "fly-connectome-sim": "Fly Connectome",
        "claude-code-kit": "Claude Code Kit",
        "manus-portfolio": "Portfolio",
    }
    if {repo["name"] for repo in data["repositories"]} != set(labels):
        raise ValueError("Unexpected activity repositories")
    totals = [0] * day_count
    series = []
    for repo in data["repositories"]:
        days = repo["daily"]
        if [day["date"] for day in days] != expected or any(type(day["count"]) is not int or day["count"] < 0 for day in days):
            raise ValueError("Invalid daily activity data")
        values = [day["count"] for day in days]
        if sum(values) != repo["total"]:
            raise ValueError("Repository activity total does not match its days")
        totals = [a + b for a, b in zip(totals, values)]
        series.append((repo, [sum(day["count"] for day in days if day["date"].startswith(month)) for month in months]))
    if data["daily"] != [{"date": day, "count": total} for day, total in zip(expected, totals)] or sum(totals) != data["total"]:
        raise ValueError("Activity totals do not match the repository data")
    peak = max((max(values) for _, values in series), default=0)
    scale = max(1, peak)
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text("In the making.", c.pad, 49, 31 if c.mobile else 35, LIGHT, True, -1)
    y = c.paragraph("A rolling log of my public project commits.", c.pad, 80, c.inner, 14, 23, MUTED)
    count_width = c.text(f'{data["total"]:,}', c.pad, y + 43, 46, ACCENT, True, -1.8)
    c.text("commits / 12 months", c.pad + count_width + 15, y + 41, 12 if c.mobile else 14, LIGHT)
    top = y + 79
    c.text("Monthly totals", c.pad, top, 12, MUTED)
    c.text(f"Shared scale: 0–{scale}", c.width - c.pad, top, 11, MUTED, anchor="end")
    chart_x = c.pad if c.mobile else c.pad + 179
    chart_w = c.inner if c.mobile else c.inner - 179
    bar_step = chart_w / 12
    colors = [ACCENT, VIOLET, CYAN, "#e2bbdb"]
    y = top + 26
    for index, (repo, monthly) in enumerate(series):
        color = colors[index]
        c.text(labels[repo["name"]], c.pad, y + 12, 14, color, True)
        if c.mobile:
            c.text(str(repo["total"]), c.width - c.pad, y + 12, 13, LIGHT, anchor="end")
            baseline = y + 75
        else:
            c.text(f'{repo["total"]:,} commits', c.pad, y + 35, 12, MUTED)
            baseline = y + 47
        c.line(chart_x, baseline, chart_x + chart_w, baseline)
        for month_index, count in enumerate(monthly):
            x = chart_x + month_index * bar_step + 2
            height = count / scale * 45
            if count:
                c.add("rect", x=number(x), y=number(baseline - height), width=number(bar_step - 4), height=number(height), rx=1.5, fill=color, opacity=".88")
            else:
                c.add("circle", cx=number(x + (bar_step - 4) / 2), cy=baseline - 2, r=1.2, fill=LINE)
        c.copy.append(f'{labels[repo["name"]]}: {repo["total"]} commits. Monthly totals: {", ".join(f"{month}: {count}" for month, count in zip(months, monthly))}.')
        y = baseline + 30
    for index, month in enumerate(months):
        if c.mobile and index not in (0, 3, 6, 9, 11):
            continue
        label = date.fromisoformat(month + "-01").strftime("%b")
        c.text(label, chart_x + (index + .5) * bar_step, y - 8, 11, MUTED, anchor="middle")
    y = c.paragraph(f'{start.strftime("%b %Y")}–{finish.strftime("%b %Y")}. Latest month through {finish.strftime("%d %b")}.', c.pad, y + 24, c.inner, 12, 20)
    y = c.paragraph("My commits on four public default branches. Work repositories and other branches are outside this view.", c.pad, y + 6, c.inner, 12, 20)
    fetched = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
    c.text(f'Snapshot · {fetched.strftime("%d %b %Y, %H:%M")} UTC', c.pad, y + 12, 11, MUTED)
    return y + 43


def club(c):
    p, w = c.pad, c.inner
    c.text("Jogge di Balla", p, 49, 31 if c.mobile else 35, bold=True, spacing=-1)
    y = c.paragraph("From a club website to running the whole night.", p, 82, w, 16, 26, LIGHT)
    y = c.paragraph("Co-founder, vice president, developer. One platform for members, orders and the screens around the venue.", p, y + 8, w, leading=24)
    y += 22
    source_x, end_x = p + 12, p + w - (110 if c.mobile else 160)
    source_w, end_w = (103, 110) if c.mobile else (174, 160)
    mid_y = y + 75
    start = source_x + source_w
    c.add("rect", x=source_x, y=mid_y - 28, width=source_w, height=56, rx=8, fill="#1c2030", stroke="#4f4666")
    c.text("Service", source_x + source_w / 2, mid_y + 5, 16, LIGHT, True, anchor="middle")
    for index, (label, detail, color) in enumerate([("Kitchen", "Food orders", ACCENT), ("Bar", "Drinks", VIOLET)]):
        row_y = y + index * 114
        wire = f"M{start} {mid_y}H{start + 19}C{start + 45} {mid_y} {end_x - 45} {row_y + 18} {end_x - 17} {row_y + 18}H{end_x}"
        c.add("path", d=wire, fill="none", stroke="#40374f", stroke_width="1.5")
        c.add("path", d=wire, fill="none", stroke=color, stroke_width="3", stroke_linecap="round", pathLength="100", **{"class": f"mm-order-route {'b' if index else 'a'}"})
        c.add("rect", x=end_x, y=row_y - 9, width=end_w, height=54, rx=8, fill="#1b2020" if not index else "#211a36", stroke="#5d7040" if not index else "#7554a9")
        c.add("rect", x=end_x, y=row_y - 9, width=end_w, height=54, rx=8, fill="none", stroke=color, stroke_width="1.5", **{"class": f"mm-order-receive {'b' if index else 'a'}"})
        c.text(label, end_x + end_w / 2, row_y + 14, 16, color, True, anchor="middle")
        c.text(detail, end_x + end_w / 2, row_y + 32, 12, MUTED, anchor="middle")
    c.add("style").text = """
      #manual-mode .mm-order-route{opacity:0;stroke-dasharray:9 110;animation:mm-order-route 8s ease-in-out infinite}
      #manual-mode .mm-order-receive{opacity:0;animation:mm-order-receive 8s ease-in-out infinite}
      #manual-mode .mm-order-route.b,#manual-mode .mm-order-receive.b{animation-delay:1.6s}
      @keyframes mm-order-route{0%,12%{stroke-dashoffset:10;opacity:0}17%{opacity:1}65%{stroke-dashoffset:-104;opacity:1}72%,100%{stroke-dashoffset:-104;opacity:0}}
      @keyframes mm-order-receive{0%,54%{opacity:0}60%{opacity:1}70%,100%{opacity:0}}
      @media(prefers-reduced-motion:reduce){#manual-mode .mm-order-route,#manual-mode .mm-order-receive{animation:none;opacity:0}}
    """
    y += 197
    items = [("Run the club", "Members, permissions and attendance."), ("Run the event", "Orders and a till for service, kitchen and bar."), ("Share the night", "Moderated photos and streaming overlays.")]
    col_width = w if c.mobile else (w - 40) / 3
    bottom = y
    for index, (title, copy) in enumerate(items):
        x = p if c.mobile else p + index * (col_width + 20)
        c.text(title, x, y, 14, LIGHT, True)
        end = c.paragraph(copy, x, y + 25, col_width, leading=23)
        bottom = max(bottom, end)
        if c.mobile:
            y = end + 17
    return bottom + 22


PROJECTS = [
    ("club", "Jogge di Balla", "Live · ongoing", "Co-founder and developer. Club membership, permissions, orders, till, live photos and streaming overlays.", "React · TypeScript · tRPC · MySQL", ACCENT),
    ("fly", "Fly Connectome Sim", "Experimental · in progress", "Connectome experiments with a simulation kernel, controlled stimulation and replay. No demonstrated learning yet.", "C++17 · Python · Node.js", VIOLET),
    ("toolkit", "Claude Code Kit", "Published toolkit", "Reusable skills, specialist agents and hooks for development, design, project upkeep and security reviews.", "Claude Code · Markdown · JavaScript hooks", ACCENT),
    ("portfolio", "manuelheller.dev", "Live", "My developer and photography portfolio. Four languages, interactive GPU ink and adaptive rendering quality.", "Next.js · React · TypeScript · WebGL/GLSL", ACCENT),
    ("shot-counter", "Shot-Counter", "Released · no longer updated", "Complete Electron app for live team shot counting, QR joining and synchronised screens. Available for Windows and Linux.", "Vue 3 · Express · SQLite · Electron", ACCENT),
    ("mercurius", "Mercurius", "Research concluded", "Trading research with reproducible backtests. Three hypotheses rejected; no real money used.", "Python · SQLite · Alpaca", MUTED),
]


def projects(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text("Projects.", c.pad, 49, 31 if c.mobile else 35, LIGHT, True, -1)
    y = c.paragraph("What I built, what it does, and where it stands.", c.pad, 82, c.inner, 14, 23)
    return y + 6


def project(c, entry):
    slug, title, status, copy, tech, color = entry
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text(title, c.pad, 38, 22, LIGHT, True, -.6)
    c.text(status, c.pad, 63, 12, color)
    x = c.pad if c.mobile else c.pad + 269
    width = c.inner if c.mobile else c.inner - 269
    y = c.paragraph(copy, x, 94 if c.mobile else 36, width, 13, 22)
    y = c.paragraph(tech, x, y + 10, width, 12, 21, CYAN)
    if slug == "fly":
        art_width = min(width, 380)
        art_height = art_width * 140 / 380
        c.art("fly", x, y + 6, art_width, art_height)
        y = y + 6 + art_height
        c.text("Stimulus / response · schematic", x, y + 13, 12, MUTED)
        return y + 35
    return max(y + 17, 99)


SKILLS = [
    ("Backend & APIs", "PHP · Yii · REST · OpenAPI", "Backend logic, API integrations and data synchronisation."),
    ("Frontend", "Vue · JavaScript · HTML · CSS", "Web interfaces and Vue components."),
    ("Data", "MySQL · MariaDB · SQLite", "Complex SQL, database design and query optimisation."),
    ("Testing & quality", "Cypress · Playwright · Vitest", "End-to-end, unit and regression tests. Visual and accessibility checks."),
    ("AI workflows", "Codex · Claude Code · MCP", "Custom skills, agents, hooks and plugins."),
    ("AI-assisted project stack", "React · TypeScript · Next.js · tRPC", "Node.js / Express, Electron, Vite, Tailwind CSS and Three.js / WebGL / GLSL."),
    ("Hosting & tooling", "Linux · nginx · Docker · Git · GitHub Actions", "Self-hosting and nginx configuration. Practical basics in Git and Docker."),
    ("Design & media", "Photography · Lightroom · Photoshop", "Graphic and web design, photo editing and video editing with DaVinci Resolve. Also Canva and GIMP."),
]


def stack(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text("Skills.", c.pad, 49, 29 if c.mobile else 35, LIGHT, True, -1)
    y = 90
    width = c.inner if c.mobile else (c.inner - 36) / 2
    row_bottom = y
    for index, (title, tech, copy) in enumerate(SKILLS):
        x = c.pad if c.mobile else c.pad + index % 2 * (width + 36)
        c.text(title, x, y, 15, LIGHT, True, -.2)
        end = c.paragraph(tech, x, y + (23 if c.mobile else 27), width, 13, 22, CYAN)
        end = c.paragraph(copy, x, end + (6 if c.mobile else 8), width, 13, 22)
        row_bottom = max(row_bottom, end)
        if c.mobile or index % 2:
            y = row_bottom + (21 if c.mobile else 29)
    return row_bottom + (22 if c.mobile else 28)


def garage(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text("After the editor.", c.pad, 52, 32 if c.mobile else 39, LIGHT, True, -1)
    c.text("My S5 B8.5. Black, low, two-piece 20s.", c.pad, 83, 13 if c.mobile else 14, ACCENT)
    art_height = c.width * 610 / 1575
    c.art("car", 0, 110, c.width, art_height)
    y = 110 + art_height + 38
    c.text("Photography.", c.pad, y, 24, VIOLET, True, -.6)
    end = c.paragraph("Cars at The ICE. Wildlife in Costa Rica. Sony α7 IV in hand.", c.pad, y + 32, c.inner)
    end = c.paragraph("Edited in Lightroom, Photoshop and DaVinci Resolve.", c.pad, end + 8, c.inner, 12, 21)
    return end + 20


EVENTS = [
    ("2014", "life", "Minecraft + Lua", "Mining turtles on my own server."),
    ("2016", "career", "Started at Novartis", "Betriebsinformatiker apprenticeship."),
    ("2019", "garage", "KTM Duke 390", "The garage started on two wheels."),
    ("2020", "career", "Earned the EFZ", "Four years of IT foundations."),
    ("2021", "career", "Into full-stack", "PHP, Vue and business applications."),
    ("2022", "club", "Founded Jogge di Balla", "Co-founder and vice president."),
    ("2023", "photo", "First camera", "Sony α7 IV."),
    ("2023", "garage", "Audi TT RS", "A new chapter on four wheels."),
    ("2024", "garage", "The S5 project", "Audi S5 B8.5."),
    ("2024", "photo", "Costa Rica, solo", "Wildlife through the lens."),
    ("2025", "career", "APIs + data sync", "Interfaces and integrations."),
    ("2025", "photo", "The ICE, St. Moritz", "Cars, winter light and Koenigsegg."),
    ("2026", "club", "Club platform live", "Service, kitchen and bar connected."),
    ("2026", "career", "Published AI toolkit", "Reusable skills and specialist agents."),
    ("2026", "career", "Trying to teach a fly", "Connectome experiments. Learning still pending."),
    ("now", "life", "Still in development", "Code, cameras, cars and club life."),
]


def history(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.heading("Life, versioned.")
    c.text("One life. A few branches.", c.pad, 73, 14, MUTED)
    c.root.find(f"{{{NS}}}desc").text = (
        "A Git-style life graph. Career, garage, photography and club branches "
        "split from a shared life spine. Dated milestones sit on their own "
        "branches, which merge back together at now. Small right-hand illustrations "
        "show a mining turtle, a checked certificate, a first photograph and "
        "a puzzled fly in a classroom. The fly is a playful metaphor, not a learning result."
    )
    colors = {
        "life": "#f1edf8",
        "career": "#dcff6b",
        "garage": "#9b78ff",
        "photo": "#82d9e4",
        "club": "#f0adcb",
    }
    lanes = {branch: c.pad + index * (12 if c.mobile else 40) for index, branch in enumerate(colors)}
    label_x = 90 if c.mobile else 245
    label_width = c.width - c.pad - label_x
    illustrations = {
        "Minecraft + Lua": "turtle",
        "Earned the EFZ": "diploma",
        "First camera": "first-photo",
        "Trying to teach a fly": "fly-classroom",
    }
    art_width = 84 if c.mobile else 112
    art_height = art_width * 64 / 120
    art_x = c.width - c.pad - art_width

    # Legend labels stay outside the lanes, leaving room for the actual forks.
    legend_x, legend_y = c.pad, 105
    for branch, color in colors.items():
        label_width_px = c.fonts[False].width(branch, 12)
        item_width = 25 + label_width_px
        if legend_x + item_width > c.width - c.pad:
            legend_x, legend_y = c.pad, legend_y + 26
        c.line(legend_x, legend_y - 4, legend_x + 15, legend_y - 4, color)
        c.add("circle", cx=legend_x + 7.5, cy=legend_y - 4, r=2.5, fill=color)
        c.text(branch, legend_x + 23, legend_y, 12, color)
        legend_x += item_width + (22 if c.mobile else 32)

    c.add("style").text = """
#manual-mode .mm-history-flow {
  stroke-dasharray: .04 .96;
  stroke-dashoffset: 1;
  opacity: 0;
  animation: mm-history-travel 14s ease-in-out infinite;
}
#manual-mode .mm-history-now { animation: mm-history-arrival 14s ease-in-out infinite; }
@keyframes mm-history-travel {
  0%, 10% { stroke-dashoffset: 1; opacity: 0; }
  14% { opacity: .95; }
  77% { stroke-dashoffset: 0; opacity: .95; }
  83%, 100% { stroke-dashoffset: 0; opacity: 0; }
}
@keyframes mm-history-arrival {
  0%, 77%, 100% { opacity: .18; }
  86% { opacity: .8; }
}
@media (prefers-reduced-motion: reduce) {
  #manual-mode .mm-history-flow { animation: none; opacity: 0; }
  #manual-mode .mm-history-now { animation: none; opacity: .3; }
}
"""

    # Size rows from wrapped copy before drawing any edges. A node always
    # belongs to its colored lane; adjacent events never become its parents.
    rows = []
    y = legend_y + 40
    for date, branch, title, context in EVENTS[:-1]:
        heading = f"{date} · {title}"
        art = illustrations.get(title)
        text_width = label_width - art_width - (12 if c.mobile else 18) if art else label_width
        heading_lines = c.wrap(heading, text_width, 14, True)
        context_lines = c.wrap(context, text_width, 12)
        row_height = max(len(heading_lines) * 21 + len(context_lines) * 19, art_height if art else 0)
        rows.append((branch, y - 5, y, heading, context, text_width, art, row_height))
        y += row_height + 12

    merge_start = y + 4
    merge_step = 20
    merge_positions = {branch: merge_start + index * merge_step for index, branch in enumerate(list(colors)[1:])}
    final_y = merge_start + 3 * merge_step + 40
    life_x = lanes["life"]
    first_y = rows[0][1]
    final_node_y = final_y - 5
    c.add("path", d=f"M{life_x} {first_y}V{final_node_y}", fill="none", stroke=colors["life"], stroke_width=1.5, opacity=".55")

    for branch in list(colors)[1:]:
        branch_rows = [row for row in rows if row[0] == branch]
        start_y = branch_rows[0][1] - 31
        end_y = merge_positions[branch]
        branch_x = lanes[branch]
        # Each branch forks from life, keeps its own history and merges back.
        # Inner lanes merge first, so the return curves do not cross live lanes.
        path = (
            f"M{life_x} {start_y} "
            f"C{life_x} {start_y + 17} {branch_x} {start_y + 13} {branch_x} {start_y + 30} "
            f"V{end_y - 28} "
            f"C{branch_x} {end_y - 11} {life_x} {end_y - 17} {life_x} {end_y}"
        )
        # Background casing makes a crossed lane distinct from a joined node.
        c.add("path", d=path, fill="none", stroke=BG, stroke_width=6, stroke_linecap="round")
        c.add("path", d=path, fill="none", stroke=colors[branch], stroke_width=1.6, stroke_linecap="round", opacity=".65")
        c.add("path", d=path, fill="none", stroke=colors[branch], stroke_width=2.6, stroke_linecap="round", pathLength=1, **{"class": "mm-history-flow"})
        c.add("circle", cx=life_x, cy=start_y, r=3, fill=BG, stroke=colors[branch], stroke_width=1.5)
        c.add("circle", cx=life_x, cy=end_y, r=3.5, fill=BG, stroke=colors[branch], stroke_width=1.5)

    for branch, node_y, baseline, heading, context, text_width, art, row_height in rows:
        color = colors[branch]
        c.add("circle", cx=lanes[branch], cy=node_y, r=7, fill=color, opacity=".09")
        c.add("circle", cx=lanes[branch], cy=node_y, r=3.5, fill=BG, stroke=color, stroke_width=1.8)
        context_y = c.paragraph(heading, label_x, baseline, text_width, size=14, leading=21, fill=LIGHT, bold=True)
        c.paragraph(context, label_x, context_y + 2, text_width, size=12, leading=19)
        if art:
            c.art(art, art_x, baseline - 14 + (row_height - art_height) / 2, art_width, art_height)

    c.add("circle", cx=life_x, cy=final_node_y, r=11, fill="none", stroke=colors["life"], stroke_width=1.2, **{"class": "mm-history-now"})
    c.add("circle", cx=life_x, cy=final_node_y, r=4.5, fill=colors["life"])
    date, branch, title, context = EVENTS[-1]
    end_y = c.paragraph(f"{date} · {title}", label_x, final_y, label_width, size=14, leading=21, fill=LIGHT, bold=True)
    end_y = c.paragraph(context, label_x, end_y + 2, label_width, size=12, leading=19)
    return end_y + 29


def footer(c):
    c.line(c.pad, 1, c.width - c.pad, 1)
    c.text("Always something in development.", c.pad, 47, 14, MUTED)
    return 80


SECTIONS = [
    ("hero", "Manuel Heller, full-stack developer", "A detailed animated camera accompanies Manuel's introduction.", hero),
    ("intro", "About Manuel", "What I build and what I enjoy outside the editor.", intro),
    *[(name, label, f"Open {label}.", partial(link_label, label=label, position=position, color=color, compact=True)) for name, label, position, color in NAV_LINKS],
    ("download-shot-counter", "Download Shot-Counter", "Download the released Electron app for Windows or Linux.", partial(link_label, label="Download Shot-Counter for Windows / Linux")),
    ("view-photography", "View my photography", "Open my photography portfolio.", partial(link_label, label="View my photography")),
    *[(name, label, "Toggle this section to read more.", partial(disclosure, label=label, subtitle=subtitle)) for name, label, subtitle in DISCLOSURES],
    ("stack", "Skills", "Backend, frontend, data, testing, AI workflows, AI-assisted project technologies, hosting and creative skills.", stack),
    ("projects", "Project overview", "All six personal projects in one linked overview, with purpose, technology and status.", projects),
    *[(f"project-{entry[0]}", entry[1], f"{entry[2]}. {entry[3]} {entry[4]}.", partial(project, entry=entry)) for entry in PROJECTS],
    ("club", "Jogge di Balla in detail", "Food and drink orders move from service to the kitchen and bar, with a brief outline highlight on arrival.", club),
    ("activity", "In the making", "Actual user-authored GitHub commits across four public project default branches, grouped into twelve calendar months by UTC committer date. The latest month may be partial. This is a dated snapshot, not the complete GitHub contribution calendar.", activity),
    ("garage", "After the editor", "Manuel's lowered black Audi S5 B8.5 in right-facing side-profile line art, with polished split-Y wheels, thin tyres and a boot-lip spoiler, followed by his photography and design work.", garage),
    ("history", "Life, versioned", "Career, garage, photography and club branches connect the milestones in Manuel's life.", history),
    ("footer", "Always something in development", "A closing note.", footer),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "manual-mode")
    parser.add_argument("--activity-data", type=Path, default=ROOT / "design" / "data" / "activity.json")
    parser.add_argument("--only", choices=[section[0] for section in SECTIONS])
    args = parser.parse_args()
    artwork = {
        key: (ROOT / "design" / "art" / filename).read_text(encoding="utf-8-sig")
        for key, filename in {
            "camera": "camera.svg",
            "car": "audi-s5.svg",
            "fly": "fly-experiment.svg",
            "turtle": "mining-turtle.svg",
            "diploma": "efz-document.svg",
            "first-photo": "first-photo.svg",
            "fly-classroom": "fly-classroom.svg",
        }.items()
    }
    artwork["animationCss"] = "@media(prefers-reduced-motion:reduce){#manual-mode *{animation:none!important}}"
    fonts = {
        False: Typeface(ROOT / "design" / "fonts" / "manrope-regular.ttf", "regular"),
        True: Typeface(ROOT / "design" / "fonts" / "manrope-bold.ttf", "bold"),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name, title, description, render in SECTIONS:
        if args.only and name != args.only:
            continue
        for mobile in (False, True):
            width = (240 if mobile else 310) if name in {item[0] for item in DISCLOSURES} else None
            canvas = Canvas(name, mobile, title, description, fonts, artwork, columns=3 if name in {link[0] for link in NAV_LINKS} else 1, width=width)
            if name == "activity":
                canvas.activity = json.loads(args.activity_data.read_text(encoding="utf-8"))
            canvas.save(render(canvas), args.output)


if __name__ == "__main__":
    main()
