# `Document`

```python
document = window.document          # or the return value of window.load_html(...)
```

A `Document` is a handle to the HTML document currently loaded in a [`Window`](window.md). It
reads and changes the live DOM, subscribes to events and owns [live bitmaps](live-bitmap.md).
There is no JavaScript: Python changes the document through these methods, and the host parses,
lays out and renders it.

Contents: [attributes](#attributes) · [generations and stale handles](#generations-and-stale-handles) ·
[events](#events) · [text, values and attributes](#text-values-and-attributes) ·
[markup and structure](#markup-and-structure) · [batches](#batches) · [queries and nodes](#queries-and-nodes) ·
[focus, selection and editing](#focus-selection-and-editing) · [forms](#forms) ·
[dialogs and popovers](#dialogs-and-popovers) · [styles and environment](#styles-and-environment) ·
[scrolling and geometry](#scrolling-and-geometry) · [resources](#resources) · [bitmaps](#bitmaps) ·
[inspection](#inspection) · [low-level `command`](#low-level-command) · [errors](#errors)

## Attributes

| Attribute | Type | Meaning |
|---|---|---|
| `window` | `Window` | The window that shows this document. |
| `id` | `str` | Opaque host document ID such as `"d3"`. Never reused within a session. |
| `MAX_HANDLERS` | `int` (class attribute) | 256: the most event callbacks one document accepts. |

## Generations and stale handles

Each load creates a new document **generation** with a new `id`. The previous `Document`, its
[`Node`](node.md) references, its event subscriptions and its bitmaps are retired at that moment.
A document is also retired by `unload()`, when its window closes, when the application shuts down,
and after a fatal `document.error`.

Every method of a retired document raises
[`StaleDocumentError`](errors.md#staledocumenterror) **locally**, before anything is sent. Events
queued for a retired document are discarded, so a late callback can never change its replacement.
Always reach the live document through `window.document` in long-lived code.

```python
old = window.document
window.load_html("<p id='x'>new</p>")
old.set_text("x", "...")     # raises StaleDocumentError
window.document.get_text("x")   # "new"
```

`element` arguments are HTML `id` values. An unknown id fails with `RpcError` -32602
("Unknown element ID"). Methods that also accept a [`Node`](node.md) say so; a node of another
document raises `ValueError`, any other type `TypeError`.

## Events

### `on`

```python
document.on(event_type: str, callback: Callable[[dict], Any], *, element: str | None = None) -> Callable[[], None]
```

Call `callback(event)` for every `event_type` event of this document. With `element`, only events
whose target is that element **or inside it** are delivered: the event's `element` (nearest
identified target) or one of the ids in its `path` (the identified bubbling route) must equal
`element`. Returns a function that removes the subscription; once it returned, the callback is not
called again, even for events already queued.

- Callbacks run on the application event thread, one at a time, in event order. They may call any
  SDK method, including other documents and windows.
- An exception in a callback is printed with its traceback to standard error and does not stop the
  other callbacks of the same event.
- Notifications arrive **after** native dispatch: a callback cannot cancel a default action
  retroactively. Use [`prevent_default`](#prevent_default) in advance.
- Raises `ValueError` once 256 callbacks are registered on the document.
- Non-bubbling events (`focus`, `blur`, `invalid`, `toggle`, `close`, ...) have a `path` with only
  their target. Subscribe to the target itself, or without `element` and filter on `event["element"]`.

The event object and all event types are described in the [events reference](events.md). The
special type `"error"` receives `{"type": "error", "message", "fatal"}` for asynchronous document
failures (see [errors](#errors)).

```python
def on_list_click(event):
    if event["element"].startswith("delete-"):
        remove_item(event["element"].removeprefix("delete-"))

unsubscribe = document.on("click", on_list_click, element="items")   # every click inside #items
```

### `prevent_default`

```python
document.prevent_default(element: str, event: str, *, prevent: bool = True, **key_modifiers) -> None
```

Register (or with `prevent=False` remove) a rule that cancels the native default action of
`event` on `element` and its descendants **before** it happens. `key_modifiers` narrows keyboard
rules: `key="Enter"`, `shift=`, `ctrl=`, `alt=`, `meta=` (booleans). Preventable events: `keydown`,
`click`, `dblclick`, `auxclick`, `contextmenu`, `beforeinput`, `copy`, `cut`, `paste`, `mousedown`,
`pointerdown`, `wheel`, `submit`, `reset`, `cancel`, `beforetoggle`. Matching events report
`default_prevented: True`. At most 256 rules per document (op `set_default_action`).

```python
document.prevent_default("editor", "keydown", key="Tab")   # keep Tab inside the editor
```

## Text, values and attributes

| Method | Returns | Op | Notes |
|---|---|---|---|
| `set_text(element, text)` | `None` | `set_text` | Replace the element's children with one text node. **Plain text**: `<b>` stays literally visible. |
| `get_text(element)` | `str` | `get_text` | Concatenated text of the element and its descendants (no separators between elements). |
| `set_value(element, value)` | `None` | `set_value` | Value of an `input`/`textarea`/`select`. Plain text. Does **not** fire `input`/`change` events. |
| `get_value(element)` | `str` | `get_value` | Current control value. |
| `set_checked(element, checked)` | `None` | `set_checked` | Checkbox/radio state; no events. |
| `get_checked(element)` | `bool` | `get_checked` | |
| `set_attribute(element, name, value)` | `None` | `set_attribute` | E.g. `("bar", "style", "width:40%")`, `("save", "disabled", "")`. |
| `remove_attribute(element, name)` | `None` | `remove_attribute` | |
| `add_class(element, name)` | `None` | `add_class` | One class name. |
| `remove_class(element, name)` | `None` | `remove_class` | |

Reading attributes has no convenience method: `document.command("get_attribute", element=..., name=...)`
returns `{"value": str | None}` and `document.command("get_attributes", element=...)` returns
`{"attributes": {...}}`. `document.command("has_element", element=...)` returns `{"exists": bool}`.

```python
document.set_text("greeting", f"Hello, {user_name}")       # safe for any user_name
document.set_attribute("progress", "style", f"width:{percent}%")
document.add_class("row-3", "selected")
```

## Markup and structure

These methods parse **trusted HTML**. Escape untrusted text with `html.escape()` first (see the
[security guide](../guides/security.md)).

| Method | Op | Notes |
|---|---|---|
| `replace_html(element, html)` | `replace_children_html` | Replace the element's children. |
| `insert_html(element, html, *, position="beforeend")` | `insert_html` | `position`: `"beforebegin"`, `"afterbegin"`, `"beforeend"`, `"afterend"`. |
| `remove(element)` | `remove_element` | Remove the element and its subtree. |

All return `None`. Moving an element is available through [`Node.move_to`](node.md#move_to) or
`document.command("move_element", element=..., target=..., position=...)`; appending text through
`document.command("append_text", element=..., text=...)` or [`Node.append_text`](node.md);
keeping only the newest children through `document.command("trim_children", element=..., keep=N,
**{"from": "start"})` ("start" removes the oldest children, "end" the newest).

```python
import html
document.insert_html("log", f"<li>{html.escape(message)}</li>")
document.replace_html("results", "".join(f"<tr><td>{html.escape(n)}</td></tr>" for n in names))
```

## Batches

### `batch`

```python
document.batch(operations: Iterable[dict]) -> None
```

Apply up to 1024 operations as **one transaction**: either all succeed or none is applied (an error
names the failing index, e.g. `batch operation 1: Unknown element ID`). Each operation is a dict
with `op` and the op's fields, addressed by `element`. Allowed ops: `set_text`, `set_attribute`,
`remove_attribute`, `add_class`, `remove_class`, `insert_html` (`position`, `html`),
`replace_children_html` (`html`), `remove_element`, `move_element` (`target`, `position`),
`append_text` (`text`), `trim_children` (`keep`, `from`).

[`node_batch`](#node_batch) is the same for [`Node`](node.md) references.

```python
document.batch([
    {"op": "insert_html", "element": "log", "position": "beforeend", "html": rows},
    {"op": "trim_children", "element": "log", "keep": 500, "from": "start"},
    {"op": "set_text", "element": "count", "text": f"{total} records"},
])
```

## Queries and nodes

### `query`

```python
document.query(selector: str, *, offset: int = 0, limit: int = 1024) -> dict
```

CSS selector query. Returns `{"ids", "total", "matched_nodes", "offset", "limit", "truncated"}`:
`matched_nodes` counts every match; `ids` lists the ids of the matches **that have an id** (and
`total` counts those). `limit` is 1–4096.

### `query_nodes`

```python
document.query_nodes(selector: str, *, offset: int = 0, limit: int = 1024) -> dict
```

Returns `{"nodes": [{"node": ref, "element": id | None}, ...], "total", "offset"}` for **all**
matches, including elements without an id. Use this to count matches and to get node references.

```python
rows = document.query_nodes("#results tr")["total"]
first = document.node(reference=document.query_nodes("li")["nodes"][0]["node"])
```

### `node`

```python
document.node(element: str | None = None, *, reference: str | None = None) -> Node
```

`node("list")` resolves an element id; `node()` returns the document node; `node(reference=ref)`
wraps a reference string returned by `query_nodes`, `children`, `inspect` or an event's `node`
member. Passing both raises `ValueError`. See [`Node`](node.md).

### `node_batch`

`document.node_batch(operations: Iterable[dict]) -> None`: like [`batch`](#batch) but each
operation names a `node` reference (and `target_node` for `move_element`).

### Other queries

| Method | Returns |
|---|---|
| `element_at_point(x, y)` | `{"element": id \| None, "node": ref}` or `None`; `x`/`y` in CSS pixels of the viewport |
| `focused_element()` | `{"element", "node"}` or `None` |

Through `command`: `text_at_point(x=, y=)` → `{"hit": {...}}`; `get_rect(element=)` →
`{"rect": {"x", "y", "width", "height"}}`; `text_rects(element=|node=, start=, end=)`;
`get_html(element=|node=, outer=False, offset=0, limit=None)` →
`{"html", "total_bytes", "offset", "next_offset", "truncated"}` (byte-paged serialisation).

## Focus, selection and editing

| Method | Returns | Notes |
|---|---|---|
| `focus(element)` | `None` | `element` is an id or a `Node`. |
| `blur(element=None)` | `None` | Without an argument blurs the focused element. |
| `control_selection(element)` | `{"start", "end", "direction", "length", "node"}` | Text-control selection. Offsets are **UTF-16 code units**, not Python string indices. |
| `set_control_selection(element, start, end, *, direction="none")` | same shape | `direction`: `"forward"`, `"backward"`, `"none"`. |
| `replace_control_range(element, replacement, *, start=None, end=None, selection_mode="preserve")` | same shape plus `changed` | Replace a range of a control's value (default: the selection). |
| `edit(command, element=None)` | `{"accepted", "clipboard_pending"}` | Run an editing command through the native editor and its undo history: `"undo"`, `"redo"`, `"cut"`, `"copy"`, `"paste"`, `"select_all"`, `"delete"`. Clipboard commands complete later; `accepted` does not mean the OS transfer succeeded. |

Document text selection through `command`: `select_text(element=)`, `get_selection()` →
`{"text"}`, `clear_selection()`, `copy_selection()`.

```python
document.set_value("notes", "hello world")
document.set_control_selection("notes", 0, 5)
document.replace_control_range("notes", "HELLO")      # "HELLO world"
document.edit("undo", "notes")                        # back to "hello world"
```

## Forms

| Method | Returns | Notes |
|---|---|---|
| `form_data(form, *, submitter=None)` | `{"entries": [...], "submitter": {"element", "node"} \| None}` | Ordered entries `{"kind": "text", "name", "value"}` or `{"kind": "file", "name", "filename", "path"}`. Repeated names (checkbox groups, multiple selects) appear once per value; unchecked boxes are absent. With `submitter`, its `name`/`value` is included. |
| `request_submit(form, *, submitter=None)` | `{"submitted": bool, "default_prevented": bool}` | Submit as if the user clicked the submitter: runs constraint validation; if valid fires `submit`, else fires `invalid` on each failing control and `submitted` is `False`. |
| `reset_form(form)` | `{"reset": bool, "default_prevented": bool}` | Restore default values; fires `reset`. |
| `validity(element)` | `{"valid", "will_validate", "message", "flags": {...}}` | `flags`: `valueMissing`, `typeMismatch`, `patternMismatch`, `tooLong`, `tooShort`, `rangeUnderflow`, `rangeOverflow`, `stepMismatch`, `badInput`, `customError`. `message` is the host's validation message. |
| `check_validity(element)` | `{"valid", "count", "invalid": [ids]}` | For a control or a whole form. |
| `set_custom_validity(element, message="")` | `{"valid", "message", "flags"}` | A non-empty message makes the control invalid (`customError`) until cleared with `""`. |
| `options(element)` | `[{"value", "label", "selected", "disabled"}, ...]` | Options of a `<select>`. |
| `set_selected_values(element, values)` | `None` | Select exactly these option values. |
| `files(element)` | `[str]` | Paths chosen in an `<input type="file">` (the host shows the native picker on click). |

`form` and `submitter` accept an id or a [`Node`](node.md); `validity`, `check_validity`,
`options`, `set_selected_values` and `files` take an id.

```python
result = document.request_submit("signup", submitter="create")
if result["submitted"]:
    values = {e["name"]: e["value"] for e in document.form_data("signup")["entries"] if e["kind"] == "text"}
```

## Dialogs and popovers

| Method | Returns | Notes |
|---|---|---|
| `show_dialog(element, *, modal=True)` | `None` | Open a `<dialog>` (`modal=False` for a non-modal dialog). |
| `close_dialog(element, return_value="")` | `None` | Close it; fires `close` with `return_value`. |
| `show_popover(element)` / `hide_popover(element)` | `None` | For elements with the `popover` attribute. |
| `toggle_popover(element)` | `bool` | The new open state. |

State through `command`: `get_dialog(element=)` → `{"open", "modal", "return_value"}` and
`get_popover(element=)` → `{"open", "kind"}`. Opening and closing fire `beforetoggle` and
`toggle` (with `old_state`/`new_state`); dialogs fire `close`, and `cancel` for a native close
request such as Escape. See the [dialogs guide](../guides/dialogs-and-popovers.md).

## Styles and environment

| Method | Returns | Notes |
|---|---|---|
| `add_stylesheet(css)` | `{"sheet": int, "diagnostics": [...]}` | Attach a stylesheet after the document's own; `sheet` identifies it. |
| `replace_stylesheet(sheet, css)` | same shape | Replace an attached sheet. |
| `remove_stylesheet(sheet)` | `None` | |
| `stylesheets()` | `[{"sheet", "kind", "href", "media", "length", "element", "node"}]` | Document `<style>`/`<link>` sheets have `sheet: None`; attached sheets have their number. |
| `computed_style(properties, element=None)` | `{"schema": 1, "properties": {name: {"value", "status", "inherited"}}}` | `element` is an id, a `Node` or `None` (document element). |
| `environment()` | `{"color_scheme", "reduced_motion", "high_contrast", "scale", "*_source", "system_*"}` | Effective media environment of this document. |
| `set_environment(*, color_scheme=None, reduced_motion=None)` | the new environment | Override what `@media (prefers-color-scheme)` and `(prefers-reduced-motion)` see. `color_scheme`: `"light"`, `"dark"`, or `"system"` to remove the override; `reduced_motion`: `"reduce"`, `"no-preference"` or `"system"`. `None` leaves a value unchanged. |

Through `command`: `css_profile()` (the supported CSS feature set) and `explain(element=, property=)`
(why a property has its value).

```python
sheet = document.add_stylesheet(".card { border-radius: 12px; }")["sheet"]
document.replace_stylesheet(sheet, ".card { border-radius: 4px; }")
document.set_environment(color_scheme="dark")
document.computed_style(["background-color"], "body")["properties"]["background-color"]["value"]
```

## Scrolling and geometry

| Method | Returns | Notes |
|---|---|---|
| `scroll(element=None)` | `{"x", "y", "min_x", "min_y", "max_x", "max_y", "width", "height", "scrollable", "animating"}` | Viewport or an element's scroll state. |
| `scroll_to(*, x=None, y=None, element=None, behavior="auto")` | same shape | `behavior`: `"auto"`, `"instant"`, `"smooth"`. |
| `scroll_into_view(element, *, block="nearest", inline="nearest")` | `None` | `block`/`inline` like CSS: `"start"`, `"center"`, `"end"`, `"nearest"`. |

Through `command`: `scroll_by(dx=, dy=, element=)` and `set_scroll_follow(element=, follow=True)`
(keep a growing container scrolled to its end, as in a log view).

## Resources

`register_resources(name, entries) -> dict` atomically replaces a named in-memory bundle for this
document, addressable as `ui4me-res://NAME/PATH` (or `nativehtmlkit-res://NAME/PATH`). `entries`
maps a path to `bytes` or `(bytes, mime_type)` (default `application/octet-stream`). At most 256
entries and 1 MiB per registration (`ValueError` locally), 16 MiB across all bundles. Returns
`{"name", "replaced"}`.

| Method | Returns |
|---|---|
| `unregister_resources(name)` | `{"name", "removed"}` |
| `resource_stats()` | `{"bundles", "cache", "svg_rasters"}` counters |
| `purge_unused_resources(url=None)` | `{"purged", "stats"}` |

```python
document.register_resources("icons", {"ok.svg": (svg_bytes, "image/svg+xml")})
document.set_attribute("status-icon", "src", "ui4me-res://icons/ok.svg")
```

## Bitmaps

`create_bitmap(bitmap_id, width, height, *, slots=2) -> LiveBitmap`: a live RGBA surface shown by
`<img src="ui4me-bitmap://BITMAP_ID">`. See [`LiveBitmap`](live-bitmap.md).

## Inspection

| Method | Returns |
|---|---|
| `diagnostics()` | `{"diagnostics": [{"code", "message", "stage"}], "css_profile_version"}`: render/layout diagnostics such as unsupported CSS or pending resources |
| `unload()` | `None`. Unload the document: the window shows no document, this handle and its nodes become stale and `window.document` is `None`. |

Through `command`: `get_accessibility_tree()` (the tree exposed to assistive technology),
`get_pointer_capture()`, `set_pointer_capture(element=, pointer_id=1, capture=True)`.

## Low-level `command`

```python
document.command(op: str, **fields) -> Any
```

Send one `document.command` operation of the Core v1 protocol and return its result. Every method
above is a thin wrapper over an op. The full op list (81 ops) and parameter schemas are part of
the Core protocol release (`protocol/v1/schemas/document-command.schema.json`); unknown ops and
unknown fields fail with `RpcError` -32602. Passing `op` twice raises `TypeError`.

Ops without a convenience method: `append_text`, `clear_selection`, `copy_selection`,
`css_profile`, `explain`, `get_accessibility_tree`, `get_attribute`, `get_attributes`,
`get_dialog`, `get_html`, `get_pointer_capture`, `get_popover`, `get_rect`, `get_selection`,
`has_element`, `move_element`, `node_children`, `get_node`, `scroll_by`, `select_text`,
`set_pointer_capture`, `set_scroll_follow`, `text_at_point`, `text_rects`, `trim_children`.

## Errors

- `StaleDocumentError`: the document was replaced, unloaded or closed (local, nothing sent).
- `ApplicationShutdownError`: `window.load_*` after shutdown began.
- `RpcError` codes: -32602 invalid argument (unknown id, bad op field), -32004 the host no longer
  knows this document, -32005 limits (for example the bitmap budget),
  -32008 wrong lifecycle phase (after shutdown began).
- Asynchronous failures arrive as `document.error`: the SDK prints the message to standard error
  and calls handlers registered with `document.on("error", ...)` with
  `{"type": "error", "message": str, "fatal": bool}`. After a fatal error the host has unloaded
  the document: it is retired and `window.document` becomes `None` (an error handler may load a
  replacement).

See [errors](errors.md) for the exception classes.
