#!/usr/bin/env python3
"""Build the launcher and a separate, credential-free HTTP document root."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile

from plus import adapt_plus

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
SITE = DIST / "server"
APPS = SITE / "apps"
ICONS = SITE / "icons"
ICON_PATH = re.compile(r"/icons/[A-Za-z0-9_-]+\.(?:png|jpe?g)", re.I)


def write(path, data, private=False):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600 if private else 0o644)
    with os.fdopen(fd, "wb") as target:
        target.write(data)
    temp.replace(path)


def pack(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(name), content, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def tree(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def module_entry(title, prefix, component, files):
    revision = hashlib.sha256(pack(files)).hexdigest()[:12]
    ident = f"{prefix}_{revision}"
    files["manifest"] += f"sg_component_libs_provided={ident}\nhidden=1\n".encode()
    data = pack(files)
    path = APPS / f"{ident}.zip"
    write(path, data)
    return {"title": title, "id": ident, "component": component, "path": f"/apps/{path.name}"}


def add_icon(entry, name, data):
    if not ICON_PATH.fullmatch("/icons/" + name):
        raise ValueError("Invalid icon filename")
    if len(data) > 2 * 1024 * 1024 or not data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        raise ValueError(f"{name}: expected a PNG or JPEG under 2 MiB")
    write(ICONS / name, data)
    entry["icon"] = "/icons/" + name


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unsupported Noir version: missing adaptation target {old[:75]!r}")
    return text.replace(old, new)


def adapt_noir(path):
    with zipfile.ZipFile(path) as archive:
        config = json.loads(archive.read("config.json")) if "config.json" in archive.namelist() else {}
        files = {
            entry.filename: archive.read(entry)
            for entry in archive.infolist()
            if not entry.is_dir() and re.fullmatch(r"(?:components|fonts)/[\w./-]+", entry.filename)
            and ".." not in Path(entry.filename).parts
            and not stat.S_ISLNK(entry.external_attr >> 16)
        }
    xml = files["components/MainScene.xml"].decode()
    xml = change(xml, 'name="MainScene" extends="Scene"', 'name="NoirModule" extends="Group"')
    xml = change(xml, "<interface>", """<interface>
<field id="dialog" type="node"/>
<field id="running" type="boolean" onChange="runningChanged"/>
<field id="focusRequested" type="boolean" alwaysNotify="true" onChange="focusRequested"/>
<field id="noirSettings" type="assocarray"/>
<field id="fontRequested" type="assocarray" alwaysNotify="true"/>
<field id="captionFont" type="node" onChange="captionFontChanged"/>
<field id="settingsChanged" type="assocarray" alwaysNotify="true"/>""")
    xml = xml.replace('uri="MainScene.brs"', 'uri="libpkg:/components/MainScene.brs"')
    xml = re.sub(r'<Font role="font" uri="pkg:/fonts/[^"]+" size="42"/>', '', xml)
    files["components/MainScene.xml"] = xml.encode()
    for name in ("BridgeTask",):
        key = f"components/{name}.xml"
        files[key] = files[key].decode().replace(f'uri="{name}.brs"', f'uri="libpkg:/components/{name}.brs"').encode()

    key = "components/MainScene.brs"
    brs = files[key].decode()
    brs = change(brs, "sub init()", "sub init()\nend sub\n\nsub startModule()")
    start = brs.index('    m.registry = CreateObject("roRegistrySection", "NoirSyncplay")')
    stop = brs.index("    m.config = invalid", start)
    brs = brs[:start] + '''    defaults = m.top.noirSettings
    m.url = ""
    m.token = ""
    if defaults.url <> invalid then m.url = defaults.url
    if defaults.token <> invalid then m.token = defaults.token
''' + brs[stop:]
    brs = change(brs, '            m.registry.Flush()', '            m.top.settingsChanged = {url: m.url, token: m.token}')
    brs = change(brs, '                m.registry.Write("url", value)\n', '')
    brs = change(brs, '                m.registry.Write("token", value)\n', '')
    brs = re.sub(r'            font = CreateObject\("roSGNode", "Font"\).*?            m.captionMeasure.font = font\n', '            m.top.fontRequested = {size: style.size, bold: style.bold}\n', brs, count=1, flags=re.S)
    if "pkg:/fonts/" in brs or "m.top.fontRequested =" not in brs:
        raise ValueError("Could not adapt the subtitle font")
    brs += '''

sub runningChanged()
    if m.top.running
        startModule()
    else
        m.tick.control = "stop"
        m.captionTimer.control = "stop"
        m.transportTimer.control = "stop"
        m.overlayTimer.control = "stop"
        if m.video.visible then m.video.control = "stop"
        if m.task <> invalid then m.task.control = "stop"
    end if
end sub

sub focusRequested()
    m.menu.SetFocus(true)
end sub

sub captionFontChanged()
    if m.captionText = invalid then return
    m.captionText.font = m.top.captionFont
    m.captionMeasure.font = m.top.captionFont
end sub
'''
    files[key] = brs.encode()
    files["manifest"] = b"title=Noir Syncplay Library\nmajor_version=1\nminor_version=0\nbuild_version=1\nrsg_version=1.3\n"
    return files, {key: config[key] for key in ("url", "token", "migrateFrom") if isinstance(config.get(key), str)}


def add_libraries(directory, entries, reserved=()):
    """Publish prebuilt SceneGraph ZIPs in the order specified in catalog.json."""
    extra = json.loads((directory / "catalog.json").read_text())
    if not isinstance(extra, list):
        raise ValueError("The extra catalog must be a JSON array")
    taken = {entry["id"].lower() for entry in entries} | {ident.lower() for ident in reserved}
    for item in extra:
        title, ident, component = (item[key] for key in ("title", "id", "component"))
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Every library needs a title")
        if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", v) for v in (ident, component)):
            raise ValueError("IDs and component names may only use letters, digits, and underscores")
        if ident.lower() in taken:
            raise ValueError(f"Duplicate library ID: {ident}")
        path = directory / f"{ident}.zip"
        data = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            flags = dict(line.split("=", 1) for line in archive.read("manifest").decode().splitlines() if "=" in line)
            if flags.get("sg_component_libs_provided") != ident:
                raise ValueError(f"{path.name}: the manifest must declare sg_component_libs_provided={ident}")
            if archive.testzip() is not None:
                raise ValueError(f"{path.name}: invalid ZIP")
        write(APPS / path.name, data)
        taken.add(ident.lower())
        entry = {"title": title, "id": ident, "component": component, "path": f"/apps/{path.name}"}
        icon = item.get("icon")
        if icon is not None:
            if not isinstance(icon, str) or not ICON_PATH.fullmatch(icon):
                raise ValueError(f"{ident}: invalid icon path")
            local_icon = directory / icon.lstrip("/")
            add_icon(entry, local_icon.name, local_icon.read_bytes())
        entries.append(entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--noir", type=Path, help="Original or recovery ZIP for Noir Syncplay")
    parser.add_argument("--server", default="", help="Initial server address; can be changed on the TV")
    parser.add_argument("--plus", type=Path, help="Original Roku Plus by JGL Customs 1.7.2 ZIP")
    parser.add_argument("--libraries", type=Path, help="Directory with library ZIPs and an extra catalog.json")
    args = parser.parse_args()

    APPS.mkdir(parents=True, exist_ok=True)
    ICONS.mkdir(parents=True, exist_ok=True)
    launcher = tree(ROOT / "roku")
    launcher["server.txt"] = args.server.encode()
    entries = []
    if args.noir:
        noir, settings = adapt_noir(args.noir)
        for name in list(noir):
            if name.startswith("fonts/"):
                launcher[name] = noir.pop(name)
        for name, content in tree(ROOT / "notices/noir").items():
            noir[name] = content
        entry = module_entry("Noir Syncplay", "noir", "NoirModule", noir)
        add_icon(entry, "noir.png", (ROOT / "artwork/noir.png").read_bytes())
        entries.append(entry)
        launcher["noir-library.txt"] = entry["id"].encode()
        launcher["noir-defaults.json"] = json.dumps(settings).encode()

    if args.plus:
        plus = adapt_plus(args.plus)
        entry = module_entry("Roku Plus · JGL Customs", "rokuplus", "PlusModule", plus)
        if "images/icon-fhd.png" in plus:
            add_icon(entry, "rokuplus.png", plus["images/icon-fhd.png"])
        entries.append(entry)
    demo = module_entry("Demo · Remote Library", "demo", "Start", tree(ROOT / "modules/demo"))
    add_icon(demo, "demo.png", (ROOT / "artwork/demo.png").read_bytes())
    if args.libraries:
        add_libraries(args.libraries, entries, reserved=(demo["id"],))
    entries.append(demo)
    write(SITE / "catalog.json", json.dumps({"version": 1, "apps": entries}, ensure_ascii=False, indent=2).encode())
    write(DIST / "roku-app-launcher.zip", pack(launcher), private=True)
    print(DIST / "roku-app-launcher.zip")
    print(SITE / "catalog.json")


if __name__ == "__main__":
    main()
