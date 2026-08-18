---
description: ASGI wiring, WebSocket JWT handshake, and the broadcast contract every working-form action owes.
paths:
  - "working_form/consumers.py"
  - "working_form/middleware.py"
  - "working_form/routing.py"
  - "working_form/views.py"
  - "evaluation_form_service/asgi.py"
---

# Real-time layer: ASGI, WebSocket auth, broadcast contract

## Wiring

The app runs under Daphne/ASGI (`ASGI_APPLICATION`); `WSGI_APPLICATION` is commented out in
settings. `evaluation_form_service/asgi.py` builds the stack in this order:

```
AllowedHostsOriginValidator( JwtAuthMiddleware( URLRouter(working_form.routing) ) )
```

Order matters: origin is checked before auth, so a non-local `Origin` header is rejected
before the token is ever read. `ALLOWED_HOSTS` is `127.0.0.1`/`localhost` only.

The two imports below `get_asgi_application()` in `asgi.py` must stay there - Channels needs
the app registry loaded first. `setup.cfg` carries a `per-file-ignores` entry for the
resulting `E402`; do not "fix" it by moving the imports up.

## Auth

`working_form/middleware.py:21 JwtAuthMiddleware` reads the JWT from the **query string**, not
from a header, because browsers cannot set headers on a WebSocket handshake. A client
connects to `ws/working_form/<form_id>/?token=<access>`.

## Routing and groups

`working_form/routing.py:6` maps `ws/working_form/<int:form_id>/` to `WorkingFormConsumer`.
The consumer joins the channel group `form_<form_id>` (`consumers.py:43`) on connect and
discards it on disconnect.

## Broadcast contract

Every mutating action on a working form must publish to that group, or connected clients
silently drift out of sync - there is no reconciliation on the client side.

Broadcasts are sent from the **views**, not the services:
`async_to_sync(channel_layer.group_send)` appears at `working_form/views.py:268, 340, 469,
553, 746, 910`. Event types currently in use:

| `type` | Sent when |
|---|---|
| `form_metadata_updated` | form fields change |
| `topic_added` | a topic is added |
| `question_added` | a question is added to a topic |
| `approval_update` | approve / unapprove |
| `handle_item_state_update` | item vote or restore |

The consumer's own inbound handlers use dotted names (`handle.item.state.update`,
`handle.topic.state.update`) - Channels maps dots to underscores when dispatching, so the
handler method is `handle_item_state_update`. Keep both spellings consistent when adding an
event.

When you add an action to `working_form/views.py`, add its broadcast in the same commit.
