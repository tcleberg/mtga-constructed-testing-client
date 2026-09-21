# Client API contract

The client uses the server's additive `/api` contract:

- `POST /api/login`: credentials, machine identity, platform and `client_version`; returns a bearer token.
- `POST /api/heartbeat`: machine identity, Arena identity and `client_version`.
- `POST /api/ingest/identity`: Arena screen name and account ID.
- `POST /api/ingest/game`: summarized game, deck, seen/played cards, mulligans, timing and turns.
- `POST /api/ingest/match`: match metadata and nested game summaries.

All routes except login require `Authorization: Bearer …`. A server must accept a new optional field before a client release sends it. Renaming or removing fields requires a new versioned endpoint.
