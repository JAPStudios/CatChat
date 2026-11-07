# CatChat

CatChat is a direct-messaging service with private one-to-one conversations, group conversations, persistent message history and read receipts. Its HTTP interface is transport-neutral and can be used by web, Android, desktop or other clients.

The repository now contains a working Flask service. It does not claim to provide connectors to WhatsApp, Facebook Messenger or other third-party messaging networks. Those require separate supported platform implementations and authorization.

## Run the service

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python catchat_server.py
```

The service listens on `127.0.0.1:7800` by default. Set `CATCHAT_HOST`, `CATCHAT_PORT` and `CATCHAT_DATABASE` to configure the listener and SQLite database. Keep the listener on loopback or behind an HTTPS reverse proxy.

Open `http://127.0.0.1:7800/` to use the responsive CatChat web client. It supports account creation, sign-in, one-to-one conversations, group conversations, message history and live message refresh. The web client can be installed as a PWA; its service worker caches only the application shell and never caches authenticated API responses. The bearer token stays in page memory and is cleared when the page is closed or the user signs out.

## Accounts and authentication

Create an account:

```http
POST /v1/accounts
Content-Type: application/json

{"username":"alice","display_name":"Alice","password":"a-long-unique-password"}
```

Passwords must contain at least 12 characters. Log in with `POST /v1/sessions` using the same username and password. The response contains a random bearer token. Send it as `Authorization: Bearer <token>` on authenticated requests. Tokens are stored as SHA-256 digests and expire after 30 days. Delete the current session with `DELETE /v1/sessions`.

## Direct and group conversations

Create a direct conversation:

```http
POST /v1/conversations/direct
Authorization: Bearer <token>
Content-Type: application/json

{"recipient_username":"bob"}
```

Create a group conversation:

```http
POST /v1/conversations/group
Authorization: Bearer <token>
Content-Type: application/json

{"name":"Project room","participants":["bob","charlie"]}
```

List conversations with `GET /v1/conversations`. Send a message with `POST /v1/conversations/{conversation_id}/messages` and body `{"content":"Message text"}`. Retrieve history with `GET /v1/conversations/{conversation_id}/messages?after_id=0&limit=50`. Mark a message as read with `POST /v1/conversations/{conversation_id}/read` and body `{"message_id":123}`. Subscribe to a bounded server-sent event stream with `GET /v1/conversations/{conversation_id}/events?after_id=123`.

Conversation membership is checked for every read, send and event request. Message bodies are limited to 4,000 characters. Request bodies are limited to 64 KiB.

## Astrologically Intelligent direct messages

CatChat reserves the username `astrologically-intelligent` for the assistant account. Creating a direct conversation with that account enables the AI reply path. Configure:

- `ASTRO_AI_BASE_URL`: the HTTPS base URL of the full Astrologically Intelligent web service.
- `ASTRO_AI_API_TOKEN`: an API token with the `chat` scope.
- `ASTRO_AI_ENDPOINT_ID`: a model endpoint registered and available to that token's owner.
- `ASTRO_AI_MODEL`: a chat model available through that endpoint.
- `CATCHAT_AI_USERNAME`: optional assistant username override; defaults to `astrologically-intelligent`.

CatChat creates one persistent Astrologically Intelligent session for each CatChat conversation through `POST /api/session` and sends messages through `POST /api/chat`. The same configured model endpoint is used for all CatChat conversations. The API token owner must be authorized to use the selected model endpoint. Each CatChat conversation has its own AI session, so its history is isolated from other conversations.

Human messages are stored in CatChat and the assistant response is stored as a normal message from the assistant account. If the AI service is unavailable, the original human message remains stored and the API returns an error rather than discarding it.

For local development, the AI base URL may use loopback HTTP. Non-loopback AI endpoints must use HTTPS.
 
## Tests

Run:

```sh
python -m unittest discover -s tests -v
```

The tests cover account creation, login, direct-message privacy, group membership, read receipts and the assistant conversation path using a mocked responder.
