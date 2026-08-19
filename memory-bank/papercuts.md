# Papercuts

- 2026-08-19 13:22:13 PDT — While consolidating branches, `git merge -F -` failed with `error: could not read file '-'`; this Git invocation does not treat `-` as stdin for merge messages, so use `git merge -m` instead.
- 2026-08-19 13:56:58 PDT — While delegating the isometric frontend to K3, the max-effort client ran for about 24 minutes without writing a file and ended with `error: provider request failed after 3 attempts: The read operation timed out`; bounded high- and low-effort retries later returned the identical error without writing a file.
- 2026-08-19 14:33:00 PDT — While starting the atlas browser smoke server, port `127.0.0.1:8765` was already owned by an unrelated Python JSON service, so the static artifact server moved to port `8766`.
- 2026-08-19 14:38:56 PDT — While checking the atlas at a mobile viewport, the T3 preview loaded and resized the page but snapshot, evaluate, click, and recording calls timed out; desktop pixels and all interactions were verified through PinchTab instead.
- 2026-08-19 14:38:56 PDT — While publishing the interactive atlas, Postplan returned `Inline JavaScript requires an authenticated upload.` and `npx postplan whoami` returned `Missing or invalid API key.`; the canonical local artifact remains complete, but mobile hosting needs Postplan authentication.
