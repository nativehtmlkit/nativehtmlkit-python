# Python SDK runtime

The SDK is a local Python API over an authenticated Core host session. `Application.start` supervises the native host and backend process; the backend sees a single app object. The transport reader/writer threads are separate from user callback execution. Notifications arrive on an event worker; close/quit requests have independent handling to avoid deadlocks.

A *released* Python SDK wheel bundles one Core host for its OS and checks its SHA-256 against `HOST-MANIFEST.json` before launching. Setting `NATIVEHTMLKIT_HOST_BINARY` is an explicit development override, not a normal install path. Never replace the bundled host silently or import internal Rust code.

Async applications use `app.async_adapter()` over the same connection, not a separate HTTP endpoint. The UI convenience library uses these public SDK handles but may not issue private Core protocol methods.
