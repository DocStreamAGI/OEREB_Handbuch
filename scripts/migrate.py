#!/usr/bin/env python3
"""Reproduzierbare ÖREB-Migration nach dem Muster der Modellierungsrichtlinien.

Konvertierung je Originalkapitel mit Node/downdoc; keine Installation auf Windows.
Liest das öffentliche SOGIS-Repository ausschliesslich lesend.
"""
from __future__ import annotations
import json
import re
import shutil
import subprocess
from pathlib import Path

SOURCE = "https://github.com/sogis/oereb-handbuch.git"
ROOT = Path("src/docs/asciidoc")
INCLUDE = re.compile(r"^include::([^\[]+)\[.*\]\s*$", re.M)
HEADING = re.compile(r"^={2,6}\s+(.+?)\s*$", re.M)
ANCHOR = re.compile(r"^\s*\[#([\w.-]+)\]\s*$", re.M)
LINK = re.compile(r"(?<!!)\]\(([^)]+)\)")
IMAGE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")

def cmd(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)

def migrate():
    repository = Path("upstream").resolve()
    if repository.exists():
        raise RuntimeError("upstream already exists; aborting instead of overwriting")
    cmd("git", "clone", "--depth", "1", "--branch", "master", SOURCE, str(repository))
    sha = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    raw_master = (repository / ROOT / "master.adoc").read_text(encoding="utf-8-sig")
    included = INCLUDE.findall(raw_master)
    if not included:
        raise RuntimeError("No chapter includes found in source master.adoc")
    sources = [(repository / path).resolve() for path in included]
    if any(not f.is_relative_to(repository) or not f.is_file() for f in sources):
        raise RuntimeError("Invalid or missing include in master.adoc")
    chapters = []
    anchors = {}
    for f in sources:
        original = f.read_text(encoding="utf-8-sig")
        m = HEADING.search(original)
        if not m:
            raise RuntimeError("Chapter without heading: " + f.name)
        chapters.append((f, m.group(1).strip()))
        for anchor in ANCHOR.findall(original):
            if anchor in anchors:
                raise RuntimeError("Duplicate anchor: " + anchor)
            anchors[anchor] = f.stem

    docs = Path("docs")
    docs.mkdir(exist_ok=True)
    image_source = repository / ROOT / "images"
    if image_source.is_dir():
        shutil.copytree(image_source, docs / "images", dirs_exist_ok=True)
    notices = []
    for f, title in chapters:
        dest = docs / (f.stem + ".md")
        cmd("npx", "--yes", "downdoc", "-o", str(dest.resolve()), str(f))
        rendered = dest.read_text(encoding="utf-8")
        if not rendered.strip() or not re.search(r"(?m)^#{1,6}\s", rendered):
            raise RuntimeError("Empty or headingless conversion: " + f.name)
        # Keep image paths relative to the final docs directory.
        def fix_image(m):
            target = m.group(2)
            if re.match(r"(?i)^https?://", target):
                return m.group(0)
            name = Path(target.split("#")[0]).name
            if (docs / "images" / name).is_file():
                return m.group(1) + "images/" + name + m.group(3)
            notices.append("Unknown image: " + f.name + " -> " + target)
            return m.group(0)
        rendered = IMAGE.sub(fix_image, rendered)
        # Convert cross-chapter anchor links to stable Markdown files.
        def fix_link(m):
            target = m.group(1).strip()
            if target.startswith("#"):
                anchor = target[1:]
                owner = anchors.get(anchor)
                if owner and owner != f.stem:
                    return "](" + owner + ".md#" + anchor + ")"
            if ".adoc" in target:
                return "](" + target.replace(".adoc", ".md") + ")"
            return m.group(0)
        rendered = LINK.sub(fix_link, rendered)
        dest.write_text(rendered.rstrip() + "\n", encoding="utf-8")

    index = ["# ÖREB-Kataster: Handbuch", "", "## Inhaltsverzeichnis", ""]
    index += ["- [" + title + "](" + f.stem + ".md)" for f, title in chapters]
    index += ["", "Quelle: [sogis/oereb-handbuch](https://github.com/sogis/oereb-handbuch)", ""]
    (docs / "index.md").write_text("\n".join(index), encoding="utf-8")
    shutil.copy2(repository / "LICENSE", "LICENSE")
    extra = sorted(str(f.relative_to(repository)) for f in (repository / ROOT / "chapter").glob("*.adoc") if f not in sources)
    broken = []
    for doc in docs.rglob("*.md"):
        for match in LINK.finditer(doc.read_text(encoding="utf-8")):
            target = match.group(1).split("#", 1)[0].split("?", 1)[0]
            if not target or target.startswith("/") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            if not (doc.parent / target).exists():
                broken.append({"file": str(doc), "target": target})
    report = {
        "source": SOURCE, "branch": "master", "source_commit": sha,
        "converter": "npx downdoc (analog Modellierungsrichtlinien)",
        "chapters": [{"title": title, "original": str(f.relative_to(repository)), "markdown": "docs/" + f.stem + ".md"} for f, title in chapters],
        "not_in_master": extra, "broken_relative_links": broken, "warnings": notices,
        "requires_editorial_review": True,
    }
    Path("migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if broken or notices:
        raise RuntimeError("Migration requires manual review: " + str(len(broken)) + " broken links, " + str(len(notices)) + " warnings")
    print("ÖREB conversion completed:", len(chapters), "chapters; source", sha)

if __name__ == "__main__":
    migrate()
