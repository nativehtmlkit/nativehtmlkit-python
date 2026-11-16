# Event objects

Callbacks registered with [`Document.on`](document.md#on) receive one `dict` per event. The host
creates it after native dispatch; the SDK adds `window_id` and `document_id`.

## Common members

| Member | Type | Meaning |
|---|---|---|
| `type` | `str` | Event type, e.g. `"click"`. |
| `element` | `str` | `id` of the nearest element with an id, starting at the target (`""` if none). |
| `path` | `list[str]` | Ids of the identified elements on the bubbling route, innermost first. For non-bubbling events only the target's entry. |
| `node` | `str` | Node reference of the actual target, usable with `document.node(reference=...)`. |
| `window_id`, `document_id` | `str` | Where the event happened. |
| `detail` | `int` | Click count for pointer events, else 0. |
| `cancelable` | `bool` | Whether the event has a cancelable default action. |
| `default_prevented` | `bool` | Present when `cancelable`: whether a [`prevent_default`](document.md#prevent_default) rule cancelled it. |
| `shift`, `ctrl`, `alt`, `meta` | `bool` | Modifier state. |

Members beginning with `_` are internal and may change.

### Control state (when the target is a form control)

| Member | Meaning |
|---|---|
| `value` | Current value of an `input`, `textarea` or `select` |
| `checked` | Checkbox/radio state |
| `selection` | `{"start", "end", "direction"}` for text controls (UTF-16 offsets) |
| `files` | Selected files of an `<input type="file">` |

### Type-specific members (present when they apply)

| Member | Events |
|---|---|
| `key`, `code`, `repeat`, `is_composing` | `keydown`, `keyup`: `key` is the logical key: the character for printable keys (`"a"`, `"A"`), otherwise a key name such as `"Enter"`, `"Escape"`, `"Tab"`, `"ArrowDown"`, `"Space"`; `code` names the physical key (`"KeyA"`, `"Enter"`) |
| `data`, `input_type` | `beforeinput`, `input`, composition events |
| `x`, `y`, `button`, `buttons` | pointer, mouse and `wheel` events (`x`/`y` in CSS pixels) |
| `delta_x`, `delta_y` | `wheel` |
| `pointer_id`, `pointer_type`, `is_primary`, `pressure` | pointer events |
| `related_node`, `related_element` | `mouseover`/`mouseout`/`focusin`/`focusout` and similar |
| `submitter` | `submit`: id of the button that submitted (if it has one) |
| `validity` | `invalid`: `{"valid", "message", "flags"}` as from [`Document.validity`](document.md#forms) |
| `old_state`, `new_state` | `beforetoggle`, `toggle` (`"open"`/`"closed"`) |
| `return_value` | `close` of a `<dialog>` |
| `property_name`, `elapsed_time`, `pseudo_element` | `transition*` |
| `animation_name`, `elapsed_time`, `pseudo_element` | `animation*` |

## Event types

The host listens for these types on every document and forwards each one; subscribe to the ones
you need:

| Group | Types |
|---|---|
| Pointer and mouse | `click`, `dblclick`, `auxclick`, `contextmenu`, `mousedown`, `mouseup`, `mousemove`, `mouseover`, `mouseout`, `mouseenter`, `mouseleave`, `pointerdown`, `pointerup`, `pointermove`, `pointercancel`, `gotpointercapture`, `lostpointercapture`, `wheel` |
| Keyboard and text | `keydown`, `keyup`, `beforeinput`, `input`, `compositionstart`, `compositionupdate`, `compositionend` |
| Focus | `focus`, `blur`, `focusin`, `focusout` |
| Forms | `change`, `submit`, `reset`, `invalid`, `select` |
| Selection and clipboard | `selectionchange`, `copy`, `cut`, `paste` |
| Dialogs and popovers | `toggle`, `beforetoggle`, `cancel`, `close` |
| Scrolling | `scroll` |
| Transitions and animations | `transitionrun`, `transitionstart`, `transitionend`, `transitioncancel`, `animationstart`, `animationiteration`, `animationend`, `animationcancel` |

Two further types come from the host rather than the DOM:

| Type | Members | When |
|---|---|---|
| `link_activated` | `element`, `href`, `url` (resolved, or `None`), `node` | A link (`<a href>`) was activated. Documents never navigate; handle this event, e.g. with [`Application.open_external`](application.md#desktop-services). |
| `environment_changed` | `environment` | The desktop preferences changed the document's media environment. |

And the SDK's own `error` type: `{"type": "error", "message", "fatal"}` for `document.error`
notifications (see [Document errors](document.md#errors)).

## Programmatic changes do not fire events

`set_value`, `set_checked`, `set_text` and the other mutation methods change the DOM without
firing `input`, `change` or similar events; they model a script assignment, not user input.
`request_submit`, `reset_form`, `show_dialog`/`close_dialog` and the popover methods do fire their
events (`submit`/`invalid`, `reset`, `beforetoggle`/`toggle`/`close`). If your handler must also
run after a programmatic change, call it yourself.

## Delegation example

```python
# <ul id="todos"><li id="todo-3"><input id="todo-3-done" type="checkbox"> ...
#   <button id="todo-3-delete">Delete</button></li></ul>

def on_click(event):
    # A click on the Delete button: element == "todo-3-delete",
    # path == ["todo-3-delete", "todo-3", "todos", ...]
    if event["element"].endswith("-delete"):
        delete(int(event["element"].split("-")[1]))

def on_change(event):
    if event["element"].endswith("-done"):
        set_done(int(event["element"].split("-")[1]), event["checked"])

document.on("click", on_click, element="todos")
document.on("change", on_change, element="todos")
```

See [events and callbacks](../guides/events-and-callbacks.md) for threading and ordering.
