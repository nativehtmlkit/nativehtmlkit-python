# More Python SDK examples

`Application` owns host session and process lifecycle; `Window` owns a native window; `Document` is replaced on load; `Document.on` returns an unsubscribe callback.

```python
window = app.open_html('<dialog id="about">Hello</dialog>')
window.document.show_dialog('about')
window.document.close_dialog('about')
paths = window.open_files(multiple=True, title='Choose files')
```

A bitmap requires `<img src="ui4me-bitmap://preview">` and `bitmap = document.create_bitmap('preview',160,90)`. Then `bitmap.present(rgba_bytes)` and `bitmap.close()`. Call `app.run()` on the owning main path. Full runnable gallery: https://github.com/nativehtmlkit/nativehtmlkit/blob/main/examples/python-sdk/gallery.py
