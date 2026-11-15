# NativeHTMLKit Python SDK — agent policy

1. Read `README.md`, `docs/QUALIFICATION.md`, and Core's published `protocol/v1` artifacts. Use the Core repo's current source only to diagnose a discrepancy, never as a build-time dependency.
2. Repository is independently buildable; no Rust compilation, Python wheel-to-PowerShell host reuse, GitHub Actions, PyPI or PSGallery publication.
3. Keep `UI4ME_ENDPOINT`, `UI4ME_TOKEN`, `UI4ME_APP_ID`, `UI4ME_PROTOCOL_VERSION` on the **internal wire-v1 environment**; public APIs remain `nativehtmlkit`.
4. Preserve source-derived behavior from the old client. Scope new features to protocol/SDK transport, typed errors, lifecycle, async and diagnostics. UI components and plugins belong elsewhere.
5. Run `bash scripts/test-local.sh`; on Linux Wayland and Windows validate the exact Core binary, user input, startup/shutdown, missed events, and cleanup. Record blocked tests honestly.
6. Errors never disappear silently; preserve original causes, stable codes and session ID. Trace records are bounded, redacted and local. No payloads or tokens in logs.
7. Application callbacks never execute on transport reader/writer threads. Synchronous APIs may block their calling thread; asyncio APIs must be awaitable and not use `.result()` on the event loop.
8. If Core is defective, create a minimal reproduction and log to Project `docs/bugs/bug_list.md`. Do not silently change Core here.
9. Do not create tags, remote releases or push without explicit user instruction. Build/verify/package locally and report SHA-256s.
10. When run from a standalone clone, use published Core contract and a local host override, not `../../` hard dependencies.
