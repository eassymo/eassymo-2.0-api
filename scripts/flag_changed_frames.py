"""Flag frames whose screens a client change touches, so super admins know to refresh the screenshot.

How it maps code to frames (eassymo-2.0-client):
- an element anchor (`data-frame="X"`, `frame="X"`, `frame: "X"`) belongs to the file it is in;
- a page anchor (`<FramePage code="X">`) also covers the component folders that page imports
  (e.g. src/components/order-management-v2/**).
Tests and stories never flag.

Run it after any UI or flow change in the client, before committing (see the workspace CLAUDE.md):
  python -m scripts.flag_changed_frames --client ../eassymo-2.0-client --base origin/dev \\
      --reason "Qué cambió en la pantalla"            # dry run: lists the frames
  ... --apply                                          # marks them "Desactualizado" in Accesos → Frames
"""
import argparse
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

CODE = r"[A-Z][A-Z0-9]*(?:\.[A-Z0-9]+)+"
ELEMENT_PATTERNS = [
    re.compile(rf'(?:data-frame|frame)="({CODE})"'),
    re.compile(rf'frame: "({CODE})"'),
]
PAGE_PATTERN = re.compile(rf'<FramePage code="({CODE})"')
DATA_FRAME_EXPR = re.compile(r"data-frame=\{([^}]*)\}")
QUOTED_CODE = re.compile(rf'"({CODE})"')
COMPONENT_IMPORT = re.compile(r"""from\s+['"](?:@/src/components|@components)/([^/'"]+)""")
IGNORED = re.compile(r"\.(test|stories)\.tsx?$")

Anchors = Dict[str, Tuple[Set[str], Set[str]]]  # file -> (codes, component dirs a page covers)


def scan_anchors(client_root: Path) -> Anchors:
    root = Path(client_root)
    anchors: Anchors = {}
    for file in (root / "src").rglob("*.tsx"):
        if not file.is_file() or IGNORED.search(file.name):  # the client has a folder named "*.tsx"
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        codes: Set[str] = set()
        for pattern in ELEMENT_PATTERNS:
            codes.update(pattern.findall(text))
        for expr in DATA_FRAME_EXPR.findall(text):
            codes.update(QUOTED_CODE.findall(expr))
        page_codes = set(PAGE_PATTERN.findall(text))
        if not codes and not page_codes:
            continue
        dirs = {f"src/components/{name}" for name in COMPONENT_IMPORT.findall(text)} if page_codes else set()
        anchors[file.relative_to(root).as_posix()] = (codes | page_codes, dirs)
    return anchors


def frames_for_changes(changed: Iterable[str], anchors: Anchors) -> Dict[str, List[str]]:
    hits: Dict[str, List[str]] = {}
    for path in changed:
        if IGNORED.search(path):
            continue
        for anchor_file, (codes, dirs) in anchors.items():
            if path == anchor_file or any(path.startswith(d + "/") for d in dirs):
                for code in codes:
                    hits.setdefault(code, [])
                    if path not in hits[code]:
                        hits[code].append(path)
    return dict(sorted(hits.items()))


def changed_files(client_root: Path, base: str) -> List[str]:
    def git(*args: str) -> List[str]:
        out = subprocess.run(["git", "-C", str(client_root), *args], capture_output=True, text=True, check=True).stdout
        return [line for line in out.splitlines() if line.strip()]

    files = git("diff", "--name-only", base) + git("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))


def current_branch(client_root: Path) -> str:
    out = subprocess.run(["git", "-C", str(client_root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True)
    return out.stdout.strip() or "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", type=Path, default=Path("../eassymo-2.0-client"))
    parser.add_argument("--base", default="origin/dev", help="branch or commit to compare with")
    parser.add_argument("--reason", required=True, help="what changed on screen (shown to super admins)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    hits = frames_for_changes(changed_files(args.client, args.base), scan_anchors(args.client))
    if not hits:
        print("No frames affected.")
        return
    for code, files in hits.items():
        print(f"{code}: {', '.join(files)}")
    if not args.apply:
        print(f"Dry run: {len(hits)} frames would be flagged. Re-run with --apply.")
        return

    from app.services import FrameAdminService

    result = FrameAdminService.flag_frames(list(hits), args.reason, f"agent:{current_branch(args.client)}")
    print(f"Flagged {len(result['flagged'])} frames.")
    if result["unknown"]:
        print(f"Not in the frames catalog (add them in Accesos or the seed): {', '.join(result['unknown'])}")


if __name__ == "__main__":
    main()
