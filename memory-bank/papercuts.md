# Papercuts

- 2026-08-19 13:22:13 PDT — While consolidating branches, `git merge -F -` failed with `error: could not read file '-'`; this Git invocation does not treat `-` as stdin for merge messages, so use `git merge -m` instead.
