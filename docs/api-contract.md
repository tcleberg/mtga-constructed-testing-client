# Client API contract

The client uses the server's additive `/api` contract:

- `GET /api/server-info`: unauthenticated. Returns `group_name` and `api_version`. Called before a password is collected so the add-group screen can name the group and refuse a server whose `api_version` exceeds `SUPPORTED_API_VERSION`.
- `POST /api/login`: credentials, machine identity, platform and `client_version`; returns a bearer token.
- `POST /api/web-handoff`: trades the bearer token for `{"path": "/auth/handoff?ticket=…"}`. The path is resolved against the server's own base URL, opened once, and never stored: the ticket is single use and expires within a minute.
- `POST /api/heartbeat`: machine identity, Arena identity and `client_version`.
- `POST /api/ingest/identity`: Arena screen name and account ID.
- `POST /api/ingest/game`: summarized game, deck, seen/played cards, mulligans, timing and turns.
- `POST /api/ingest/match`: match metadata and nested game summaries.

All routes except `/api/server-info` and login require `Authorization: Bearer …`. A server must accept a new optional field before a client release sends it. Renaming or removing fields requires a new versioned endpoint.

A client may be signed in to several groups at once. Each group is a wholly separate deployment with its own account, token, and queue, so every call above is made once per group and nothing is shared between them.
