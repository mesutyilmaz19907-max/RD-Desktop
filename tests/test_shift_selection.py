from types import SimpleNamespace

from rdclient.app import RubberBandSelector


class FakeTree:
    def __init__(self):
        self.children = ("a", "b", "c", "d", "e")
        self.selected = ()
        self.focused = ""
        self.row_for_y = {}
        self.seen = []

    def bind(self, *_args, **_kwargs):
        return None

    def get_children(self):
        return self.children

    def identify_row(self, y):
        return self.row_for_y.get(y, "")

    def selection(self):
        return self.selected

    def selection_set(self, items, *extra):
        if extra:
            values = (items, *extra)
        elif isinstance(items, str):
            values = (items,)
        else:
            values = tuple(items)
        self.selected = tuple(values)

    def selection_remove(self, items):
        remove = {items} if isinstance(items, str) else set(items)
        self.selected = tuple(i for i in self.selected if i not in remove)

    def focus(self, iid=None):
        if iid is None:
            return self.focused
        self.focused = iid

    def see(self, iid):
        self.seen.append(iid)


def event(y, state=0):
    return SimpleNamespace(x=10, y=y, state=state)


def test_first_shift_click_uses_first_plain_click_as_anchor():
    tree = FakeTree()
    selector = RubberBandSelector(tree)
    tree.row_for_y = {10: "b", 40: "e"}

    # The selector sees the initial press before ttk performs its normal click.
    assert selector.press(event(10)) is None
    tree.selection_set("b")
    tree.focus("b")

    result = selector.press(event(40, RubberBandSelector.SHIFT_MASK))

    assert result == "break"
    assert tree.selection() == ("b", "c", "d", "e")
    assert tree.focus() == "e"


def test_shift_click_selects_reverse_range():
    tree = FakeTree()
    selector = RubberBandSelector(tree)
    tree.row_for_y = {10: "d", 40: "b"}

    selector.press(event(10))
    tree.selection_set("d")
    tree.focus("d")
    selector.press(event(40, RubberBandSelector.SHIFT_MASK))

    assert tree.selection() == ("b", "c", "d")


def test_ctrl_shift_adds_range_to_existing_selection():
    tree = FakeTree()
    selector = RubberBandSelector(tree)
    tree.row_for_y = {10: "b", 40: "d"}

    selector.press(event(10))
    tree.selection_set(("a", "b"))
    tree.focus("b")
    selector.press(event(40, RubberBandSelector.SHIFT_MASK | RubberBandSelector.CTRL_MASK))

    assert tree.selection() == ("a", "b", "c", "d")


def test_blank_plain_click_clears_selection_and_anchor():
    tree = FakeTree()
    selector = RubberBandSelector(tree)
    selector.anchor = "c"
    tree.selected = ("b", "c")
    tree.row_for_y = {99: ""}

    selector.press(event(99))

    assert tree.selection() == ()
    assert selector.anchor is None


def test_native_tree_first_shift_click_selects_full_range(ui_root):
    import tkinter.ttk as ttk

    tree = ttk.Treeview(ui_root, columns=("name",), show="headings", selectmode="extended")
    tree.heading("name", text="Name")
    tree.pack(fill="both", expand=True)
    for i in range(5):
        tree.insert("", "end", iid=str(i), values=(f"item {i}",))
    selector = RubberBandSelector(tree)
    ui_root.update()

    def click(iid, *, state=0):
        x, y, _w, h = tree.bbox(iid)
        x += 10
        y += h // 2
        tree.event_generate("<ButtonPress-1>", x=x, y=y, state=state)
        tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=state)
        ui_root.update()

    click("1")
    assert tree.selection() == ("1",)
    assert selector.anchor == "1"

    click("4", state=RubberBandSelector.SHIFT_MASK)
    assert tree.selection() == ("1", "2", "3", "4")
