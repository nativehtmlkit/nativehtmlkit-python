# Security

NativeHTMLKit runs no JavaScript and loads no remote content over HTTP, so classic web XSS cannot
execute code. Markup injection still matters: untrusted text interpreted as HTML can rearrange your
UI, spoof controls or hide information. Treat the page like any other UI that shows untrusted data.

## Text is safe, markup is trusted

| Safe for any string | Parses HTML: trusted input only |
|---|---|
| `set_text`, `set_value`, `Node.set_text`, `append_text`, batch `set_text`, `set_attribute` values | `replace_html`, `insert_html`, `Node.insert_html`/`replace_html`, batch `insert_html`/`replace_children_html`, `load_html` |

Escape every untrusted value you put into markup, including attribute values:

```python
import html
row = (f'<li id="file-{index}" title="{html.escape(path_text)}">'
       f'{html.escape(file_name)}</li>')
document.insert_html("files", row)
```

`html.escape` escapes `&`, `<`, `>`, `"` and `'` (with the default `quote=True`), which covers text
and quoted attribute values. Never put untrusted data into element ids, tag names, unquoted
attributes, `style` or CSS: build those from your own values (numbers, known keys) and map them
back in Python, as the examples do with `id="todo-7-delete"`.

Untrusted text includes user input, file names and contents, clipboard text, network data,
command-line arguments and anything read back from the document.

## Trusted HTML and CSS

Markup and styles you ship with the application are trusted. Load them from your package
(`load_file`) or constants. Do not load HTML files chosen by the user as documents; show their text
with `set_value`/`set_text` instead.

`add_stylesheet` and `register_resources` take trusted content too; never build CSS from untrusted
strings.

## Links and external targets

Documents never navigate; a link activation only sends `link_activated` to Python. Decide
explicitly what to open, and check the scheme yourself before calling `open_external`:

```python
def on_link(event):
    url = event.get("url") or ""
    if url.startswith(("https://", "mailto:")):
        app.open_external(url, window=window)
```

The host itself refuses schemes other than `http`, `https`, `mailto` and `file` (and executable
files on Windows).

## Files

- Paths from dialogs and forms are chosen by the user, but their **content** is still untrusted:
  limit sizes, decode explicitly, handle errors.
- Write application data atomically into the per-application directories (`desktop.paths`).

## Process and credentials

- The host connection is a private local endpoint (a Unix socket in a 0700 runtime directory, or a
  named pipe restricted to the current logon session) and requires a single-use launch token. The
  SDK removes the token from `os.environ` when it connects, so child processes you start do not
  inherit it.
- Diagnostics never record payloads or form values. `--host-log`/`NATIVEHTMLKIT_HOST_LOG` writes
  raw host records that include your application's output: treat those files as sensitive.
- `NATIVEHTMLKIT_HOST_BINARY` runs an unverified host; use it only for development. The bundled host
  is checked against its pinned SHA-256 on every launch.
