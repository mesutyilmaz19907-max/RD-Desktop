from rdclient.app import RDModernApp, _timestamp_sort_key


class FakeTree:
    def __init__(self):
        self._columns = ("name", "size", "added")
        self._headings = {c: {"text": c.title(), "command": None} for c in self._columns}
        self._children = ["a", "b", "c"]

    def __getitem__(self, key):
        if key == "columns":
            return self._columns
        raise KeyError(key)

    def heading(self, column, option=None, **kwargs):
        if kwargs:
            self._headings[column].update(kwargs)
        if option is not None:
            return self._headings[column][option]
        return dict(self._headings[column])

    def get_children(self, _item=""):
        return tuple(self._children)

    def move(self, iid, _parent, position):
        self._children.remove(iid)
        self._children.insert(position, iid)


def test_tree_heading_sorting_toggles_direction_and_marks_header():
    app = RDModernApp.__new__(RDModernApp)
    tree = FakeTree()
    data = {
        "a": {"name": "Zulu", "size": 20},
        "b": {"name": "alpha", "size": 5},
        "c": {"name": "Mike", "size": 10},
    }
    app._enable_tree_sorting(
        tree,
        {
            "name": lambda iid: data[iid]["name"],
            "size": lambda iid: data[iid]["size"],
            "added": lambda _iid: None,
        },
    )
    app._sort_tree(tree, "name")
    assert tree.get_children() == ("b", "c", "a")
    assert tree.heading("name", "text").endswith("▲")
    app._sort_tree(tree, "name")
    assert tree.get_children() == ("a", "c", "b")
    assert tree.heading("name", "text").endswith("▼")


def test_tree_numeric_sort_uses_numbers_not_display_text():
    app = RDModernApp.__new__(RDModernApp)
    tree = FakeTree()
    values = {"a": 1024, "b": 10, "c": 100}
    app._enable_tree_sorting(tree, {"name": lambda iid: iid, "size": lambda iid: values[iid], "added": lambda _iid: None})
    app._sort_tree(tree, "size")
    assert tree.get_children() == ("b", "c", "a")


def test_timestamp_sort_key_handles_real_debrid_zulu_time():
    assert _timestamp_sort_key("2026-10-10T05:41:01.000Z") < _timestamp_sort_key("2026-10-11T05:41:01.000Z")
