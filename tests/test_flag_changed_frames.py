from pathlib import Path

from scripts import flag_changed_frames as script


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _client(tmp_path):
    src = tmp_path / "src"
    _write(src, "components/my-team/my-team.tsx", '<Stack data-frame="C.WG.3.L">')
    _write(src, "common/components/side-drawer/side-drawer.tsx", 'frame: "C.WG.1.M",\n<DrawerCta frame={cta.frame} />')
    _write(src, "components/dashboard-v2/dashboard-v2.tsx", '<Box data-frame={x ? "V.N3.S1" : "C.N3.S1"}>')
    _write(src, "pages/order-management-v2/index.tsx",
           "import { OrderManagementV2 } from '@components/order-management-v2/order-management-v2';\n"
           '<FramePage code="C.N3.S4"><OrderManagementV2 /></FramePage>')
    _write(src, "pages/messages/index.tsx",
           'import { MessagesInbox } from "@/src/components/messages-inbox/messages-inbox";\n'
           '<FramePage code="SCC.M.3"><MessagesInbox /></FramePage>')
    _write(src, "components/unrelated/thing.tsx", "export const X = 1;")
    return tmp_path


def test_scan_finds_element_and_page_anchors_with_page_component_dirs(tmp_path):
    anchors = script.scan_anchors(_client(tmp_path))
    assert anchors["src/components/my-team/my-team.tsx"] == ({"C.WG.3.L"}, set())
    assert anchors["src/components/dashboard-v2/dashboard-v2.tsx"][0] == {"V.N3.S1", "C.N3.S1"}
    assert anchors["src/pages/order-management-v2/index.tsx"] == (
        {"C.N3.S4"}, {"src/components/order-management-v2"})
    assert anchors["src/pages/messages/index.tsx"][1] == {"src/components/messages-inbox"}


def test_changed_files_map_to_frames(tmp_path):
    anchors = script.scan_anchors(_client(tmp_path))
    hits = script.frames_for_changes([
        "src/components/my-team/my-team.tsx",                                  # anchor file itself
        "src/components/order-management-v2/components/order-item/order-item.tsx",  # inside a page's component
        "src/components/unrelated/thing.tsx",                                  # no frame
        "README.md",
    ], anchors)
    assert hits == {
        "C.WG.3.L": ["src/components/my-team/my-team.tsx"],
        "C.N3.S4": ["src/components/order-management-v2/components/order-item/order-item.tsx"],
    }


def test_test_and_story_files_do_not_flag(tmp_path):
    anchors = script.scan_anchors(_client(tmp_path))
    assert script.frames_for_changes([
        "src/components/my-team/my-team.test.tsx",
        "src/components/order-management-v2/order-management-v2.stories.tsx",
    ], anchors) == {}


def test_folders_named_like_tsx_files_are_skipped(tmp_path):
    client = _client(tmp_path)
    (client / "src/components/invite-dialog-v2.tsx").mkdir(parents=True)
    assert "src/components/my-team/my-team.tsx" in script.scan_anchors(client)
