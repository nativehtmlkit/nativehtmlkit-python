# How-to guides

Task-oriented recipes for the NativeHTMLKit Python SDK 0.1.2. New to the SDK? Start with
[getting started](../getting-started.md) and the [todo tutorial](../tutorials/todo-app.md). Exact
signatures are in the [API reference](../API.md).

| Guide | You want to… |
|---|---|
| [Application lifecycle](lifecycle.md) | choose an entry point; quit, close and shutdown hooks |
| [Events and callbacks](events-and-callbacks.md) | react to clicks and typing; delegate events; know which thread runs your code |
| [Updating the page](updating-the-page.md) | change text, attributes and classes; render lists and tables; batch updates |
| [Forms and validation](forms-and-validation.md) | read form values, use HTML validation, add custom rules |
| [Multiple windows and window state](windows.md) | open several windows, resize/rename them, veto closing |
| [Native file dialogs](file-dialogs.md) | let the user open, save or choose a folder |
| [HTML dialogs and popovers](dialogs-and-popovers.md) | show modal `<dialog>`s and `popover` elements |
| [Clipboard and desktop services](clipboard-and-desktop.md) | copy/paste, open links and files, follow the desktop theme |
| [Keyboard and focus](keyboard-and-focus.md) | add shortcuts, keep Tab in an editor, move focus, edit the selection |
| [Styling and layout](styling-and-layout.md) | know which CSS works, lay out a window, light/dark mode, change styles at run time |
| [Live bitmaps](live-bitmaps.md) | draw charts or images from Python pixels |
| [Background work](background-work.md) | run slow or periodic work without freezing the window |
| [Diagnostics and troubleshooting](diagnostics-and-troubleshooting.md) | find out why something does not happen; build an About/Support window |
| [Packaging and distribution](packaging-and-distribution.md) | ship an application to users |
| [Project scaffolding](project-scaffolding.md) | start a project with `nativehtmlkit-new`, grow and test it |
| [Security](security.md) | handle untrusted text, files and links safely |

Python-specific:

| Guide | You want to… |
|---|---|
| [asyncio integration](asyncio.md) | write async callbacks and awaitable updates |

Every guide links to runnable applications; the full list is in
[examples/README.md](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md).
