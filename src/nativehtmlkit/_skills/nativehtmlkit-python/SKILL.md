# NativeHTMLKit Python SDK — Coding Agent Reference

Read the `nativehtmlkit-python` repository's `AGENTS.md`, public Core v1 contract, and package README.
Use `Application.from_environment()` when launched by Core; `Application.start()` for direct scripts; `python -m nativehtmlkit run MODULE:CALLABLE` to avoid double-running module initialization.
Use `AsyncRpcClient` or `AsyncApplication` with `asyncio` for nonblocking callbacks. The host's native event loop is independent from the SDK transport; never block callback dispatch with long work.
Keep UI components, plugins, and application logic outside this repository.
Never include secrets, RPC params/results, or user text in debug reports. Run local tests; never use GitHub Actions.
