def test_tree_headings_match_cell_alignment(ui_app):
    tree=ui_app.torrent_tree
    for key in tree['columns']:
        assert str(tree.heading(key,'anchor'))==str(tree.column(key,'anchor'))


def test_torrent_upload_controls_are_vertically_centered(ui_app):
    ui_app.nb.select(1)
    ui_app.root.update()
    upload,magnet=ui_app.upload_torrent_btn,ui_app.add_magnet_btn
    row=upload.master
    for button in (upload,magnet):
        center=button.winfo_y()+button.winfo_height()/2
        assert abs(center-row.winfo_height()/2)<=1
