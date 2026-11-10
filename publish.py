#!/usr/bin/env python3
"""Rebuilds this Feather / AltStore source from the IPAs listed in APPS, then commits and pushes.

Usage: ./publish.py            rebuild, commit, push
       ./publish.py --no-push  rebuild only, to look at the result first

To add an app: build its unsigned IPA, add an entry to APPS, run this.
"""
import datetime
import hashlib
import json
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
RAW = "https://raw.githubusercontent.com/MEDSYNAPSE/sideload/main"
PROJECTS = pathlib.Path.home() / "projects"

# This repo is public. Only list an app here once its IPA has been checked for private content:
# real names, recorded voices, photos, keys, and any wording that still needs sign-off.
APPS = [
    dict(
        slug="scope",
        ipa=PROJECTS / "scope/build/Scope.ipa",
        icon=PROJECTS / "scope/Scope/Assets.xcassets/AppIcon.appiconset/AppIcon.png",
        category="utilities",
        tint="FFB554",
        subtitle="Camera on one device, monitor on another.",
        description="Turns one iPhone or iPad into a camera and another into its monitor. Live picture and sound over "
                    "your own Wi-Fi, encrypted, paired with a family code. No account and nothing uploaded.\n\n"
                    "Not a medical or safety device. It does not replace an adult checking on a child.",
    ),
    dict(
        slug="ripple-chess",
        ipa=PROJECTS / "chess-coach/ios/build/RippleChess.ipa",
        icon=PROJECTS / "chess-coach/ios/App/Assets.xcassets/AppIcon.appiconset/icon-1024.png",
        category="games",
        tint="3B82C4",
        subtitle="Chess that shows what each move causes.",
        description="A chess trainer. After every move it shows the consequences as a picture and a plain analogy, "
                    "with lessons, five opponent levels and five themes.",
    ),
    dict(
        slug="setmate",
        ipa=PROJECTS / "setmate/build/Setmate-1.1-unsigned.ipa",
        icon=PROJECTS / "setmate/setmate/Assets.xcassets/AppIcon.appiconset/AppIcon.png",
        category="lifestyle",
        tint="C8FF3D",
        subtitle="Set timer, routines and training log.",
        description="A gym companion. Times sets and rests, builds routines from a 622-exercise library, keeps your "
                    "history and suggests the next weight. A Mind section covers eating patterns with check-ins, short "
                    "lessons and an urge timer.\n\n"
                    "General information only. Not medical advice and not a treatment for an eating disorder.",
    ),
    dict(
        slug="tidy-dash",
        ipa=PROJECTS / "tidy-dash/build/TidyDash.ipa",
        icon=PROJECTS / "tidy-dash/TidyDash/Assets.xcassets/AppIcon.appiconset/AppIcon.png",
        category="games",
        tint="F5B841",
        subtitle="A tidy-up race for the whole family.",
        description="Turns cleaning a room into a race. Prop the phone in the middle, put one thing away, run back "
                    "and hit your pad. Surprise rounds, a Mess Monster to beat together, and a mystery prize for the "
                    "winner that parents choose.\n\n"
                    "Stars and a race track let small children follow their score. No account and nothing uploaded.",
    ),
    dict(
        slug="magic-playground",
        # Build 1 carried narration in an Apple system voice, licensed for personal use only. Never publish it.
        min_build=2,
        ipa=pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Magic Playground/MagicPlayground.ipa",
        icon=PROJECTS / "magic-playground/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png",
        category="games",
        tint="8B5CF6",
        subtitle="Fourteen floor-play games for small children.",
        description="Movement and party games for toddlers and the grown-ups with them: statues, Simon says, "
                    "treasure hunts and story adventures, with narration and music. Floor-level play only. "
                    "A grown-up awards the stars.\n\n"
                    "Music and sound credits are in the app under Settings.",
    ),
]

# A build made on this Mac carries the home folder's path, and so its owner's name, in its debug symbols.
PRIVATE_PATH = re.compile(rb"/Users/[A-Za-z0-9._-]+|-Users-[A-Za-z0-9._-]+-")
MACH_O = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")


def publishable_copy(ipa, dest):
    """Writes a copy of the IPA with debug symbols stripped, and refuses if a home-folder path is still inside."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["unzip", "-q", str(ipa), "-d", tmp], check=True)
        files = [f for f in pathlib.Path(tmp).rglob("*") if f.is_file() and not f.is_symlink()]
        for f in files:
            with open(f, "rb") as handle:
                magic = handle.read(4)
            if magic in MACH_O:
                subprocess.run(["strip", "-S", str(f)], check=True, capture_output=True)
        for f in files:
            found = PRIVATE_PATH.search(f.read_bytes())
            if found:
                sys.exit(f"{ipa.name}: {f.name} still contains a home-folder path ({found.group(0)[:12].decode()}...). Not published.")
        packed = pathlib.Path(tmp) / "out.ipa"
        subprocess.run(["zip", "-qry", str(packed), "Payload"], check=True, cwd=tmp)
        shutil.copyfile(packed, dest)


def read_ipa(path):
    """Returns the app's Info.plist. Refuses an IPA that carries a provisioning profile."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if any(n.endswith("embedded.mobileprovision") for n in names):
            sys.exit(f"{path.name}: contains a provisioning profile (device IDs, team details). Publish the unsigned build.")
        plist = next(n for n in names if n.count("/") == 2 and n.endswith(".app/Info.plist"))
        return plistlib.loads(z.read(plist))


def entry(app):
    ipa = app["ipa"]
    if not ipa.exists():
        sys.exit(f"missing IPA: {ipa}")
    if not app["icon"].exists():
        sys.exit(f"missing icon: {app['icon']}")
    info = read_ipa(ipa)
    slug = app["slug"]
    (ROOT / "ipa").mkdir(exist_ok=True)
    (ROOT / "icons").mkdir(exist_ok=True)
    if int(info["CFBundleVersion"]) < app.get("min_build", 0):
        sys.exit(f"{ipa.name}: build {info['CFBundleVersion']} is older than the first publishable build {app['min_build']}")
    # Stripping and zipping never give the same bytes twice, so redo the copy only when the source IPA changes.
    published = ROOT / "ipa" / f"{slug}.ipa"
    digest = hashlib.sha256(ipa.read_bytes()).hexdigest()
    if SOURCES.get(slug) != digest or not published.exists():
        publishable_copy(ipa, published)
        SOURCES[slug] = digest
    subprocess.run(["sips", "-Z", "256", str(app["icon"]), "--out", str(ROOT / "icons" / f"{slug}.png")],
                   check=True, capture_output=True)
    version = info["CFBundleShortVersionString"]
    date = datetime.datetime.fromtimestamp(ipa.stat().st_mtime).astimezone().replace(microsecond=0).isoformat()
    download = f"{RAW}/ipa/{slug}.ipa"
    size = published.stat().st_size
    return {
        "name": info.get("CFBundleDisplayName") or info["CFBundleName"],
        "bundleIdentifier": info["CFBundleIdentifier"],
        "developerName": "Rise Labs",
        "subtitle": app["subtitle"],
        "localizedDescription": app["description"],
        "iconURL": f"{RAW}/icons/{slug}.png",
        "tintColor": app["tint"],
        "category": app["category"],
        # Newer readers use "versions". Older ones read the four fields after it.
        "versions": [{
            "version": version,
            "buildVersion": info["CFBundleVersion"],
            "date": date,
            "downloadURL": download,
            "size": size,
            "minOSVersion": info.get("MinimumOSVersion", "16.0"),
        }],
        "version": version,
        "versionDate": date,
        "downloadURL": download,
        "size": size,
        "appPermissions": {
            "entitlements": [],
            "privacy": {k: v for k, v in info.items() if k.startswith("NS") and k.endswith("UsageDescription")},
        },
    }


SOURCES = {}


def main():
    record = ROOT / "sources.json"   # sha256 of each source IPA last published
    SOURCES.update(json.loads(record.read_text()) if record.exists() else {})
    apps = [entry(app) for app in APPS]
    record.write_text(json.dumps(SOURCES, indent=2) + "\n")
    source = {
        "name": "Rise Labs",
        "identifier": "nz.pasifikarise.sideload",
        "subtitle": "Home-made apps, unsigned, for sideloading.",
        "sourceURL": f"{RAW}/apps.json",
        "iconURL": apps[0]["iconURL"],
        "tintColor": "FFB554",
        "nsfw": False,
        "apps": apps,
        "news": [],
    }
    (ROOT / "apps.json").write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    for app in apps:
        print(f"{app['name']:<16} {app['version']:<8} {app['size'] / 1e6:.1f} MB")
    if "--no-push" in sys.argv:
        return
    git = lambda *args: subprocess.run(["git", "-C", str(ROOT), *args], check=True)
    git("add", "-A")
    if subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--quiet"]).returncode == 0:
        print("nothing changed")
        return
    summary = ", ".join(f"{a['name']} {a['version']}" for a in apps)
    git("commit", "-q", "-m", f"Publish {summary}")
    git("push", "-q")
    print("pushed")


if __name__ == "__main__":
    main()
