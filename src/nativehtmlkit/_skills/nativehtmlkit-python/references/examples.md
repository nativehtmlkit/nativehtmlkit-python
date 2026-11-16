# More Python SDK examples

`Application` owns the host session and process lifecycle; `Window` owns a native window; `Document` is replaced on every load; `Document.on` returns an unsubscribe callback.

## Delegated list with escaping

```python
import html

def render(items):
    document.replace_html('items', ''.join(
        f'<li id="item-{i}">{html.escape(text)} <button id="item-{i}-delete">Delete</button></li>'
        for i, text in enumerate(items)))

def on_click(event):
    parts = event['element'].split('-')          # "item-3-delete"
    if len(parts) == 3 and parts[2] == 'delete':
        del items[int(parts[1])]
        render(items)

document.on('click', on_click, element='items')
```

## Form submit and validation

```python
def on_submit(event):
    values = {e['name']: e.get('value', '') for e in document.form_data('signup')['entries']}
    document.set_text('result', f"Welcome, {values['name']}")

document.on('submit', on_submit, element='signup')
document.on('invalid', lambda e: print(e['element'], e['validity']['message']))   # does not bubble
document.set_custom_validity('confirm', 'Passwords differ')   # '' clears it
```

## Non-blocking file dialog

```python
from nativehtmlkit import RpcError

def done(future):
    try:
        result = future.result()                 # {'cancelled': bool, 'paths': [...]}
    except RpcError as error:                    # -32001: no dialog service / headless
        document.set_text('status', f'No dialog ({error.code})')
        return
    if not result['cancelled']:
        document.set_value('editor', open(result['paths'][0], encoding='utf-8').read())

window.open_files(filters=[{'name': 'Text', 'extensions': ['txt', 'md']}], wait=False).add_done_callback(done)
```

## Background thread with batched updates

```python
import html
import threading
from nativehtmlkit import NativeHTMLKitError

stop = threading.Event()
app.on_shutdown(stop.set)

def worker():
    for n, line in enumerate(source(), 1):
        if stop.is_set():
            return
        try:
            document.batch([
                {'op': 'insert_html', 'element': 'log', 'position': 'beforeend', 'html': f'<div>{html.escape(line)}</div>'},
                {'op': 'trim_children', 'element': 'log', 'keep': 500, 'from': 'start'},
                {'op': 'set_text', 'element': 'count', 'text': str(n)}])
        except NativeHTMLKitError:
            return                               # window closed or shutting down

threading.Thread(target=worker, daemon=True).start()
```

## Dialogs, popovers, bitmaps, windows

```python
window = app.open_html('<dialog id="about">Hello</dialog><div id="tip" popover>Tip</div>'
                       '<img src="ui4me-bitmap://preview" width="160" height="90">')
window.document.show_dialog('about')
window.document.close_dialog('about', 'ok')      # fires "close" with return_value
window.document.toggle_popover('tip')
bitmap = window.document.create_bitmap('preview', 160, 90)
bitmap.present(bytes((40, 90, 200, 255)) * (160 * 90))
window.on_before_close(lambda: not editor_dirty)  # False keeps the window open
window.set(title='Edited', width=800, height=600)
```

Call `app.run()` on the owning main path. Fifteen runnable applications (hello, async counter, todo list, sign-up form, log viewer, settings dialog, file viewer, window manager, live chart, text toolbox, async jobs, checksums, data table, DOM explorer, focus timer) are indexed at https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md; the public gallery is https://github.com/nativehtmlkit/nativehtmlkit/blob/main/examples/python-sdk/gallery.py
