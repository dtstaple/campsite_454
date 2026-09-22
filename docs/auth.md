# Auth and saved campsites

Registration, login, and per-user saved campsites, added in TM05-16. Foundation for later
user-specific features (trip planning) — nothing here needs the map data API to change.

The server runs at `http://localhost:8000` by default (`python manage.py runserver` from
`backend/`).

---

## Token approach

DRF's built-in token auth (`rest_framework.authtoken`) — one opaque token per user, no
expiry, no refresh flow. No new dependency; simpler than JWT for what this story needs.

Attach it to any authenticated request as:

```
Authorization: Token <token>
```

---

## Endpoints

| Endpoint | Method | Auth required | Returns |
|---|---|---|---|
| `/api/auth/register/` | `POST` | No | `201` with the new account |
| `/api/auth/login/` | `POST` | No | `200` with a token |
| `/api/saved-campsites/<campsite_id>/` | `POST` | Yes | `201` (or `200` if already saved) |
| `/api/saved-campsites/<campsite_id>/` | `DELETE` | Yes | `204` |

---

## Register

```
POST /api/auth/register/
{ "username": "rania", "email": "rania@example.com", "password": "a-strong-passw0rd!" }
```

`201`:

```json
{ "username": "rania", "email": "rania@example.com" }
```

Passwords run through Django's standard validators (length, common-password, similarity
to username/email, not fully numeric) — a rejected password comes back as `400` with the
specific reason(s):

```json
{ "password": ["This password is too common."] }
```

A taken **username** is a normal `400`:

```json
{ "username": ["That username is already taken."] }
```

A taken **email** is deliberately *not* reported. Registering with an email that already
has an account still returns `201` with the same shape as a fresh registration, and
silently does not create a second account. This is intentional: an endpoint that responds
differently for "new" vs. "email already registered" lets an attacker use registration to
check who has an account here. If a registration call succeeds but a later login for that
username fails, the email was already taken — no signal is ever given at register time.

---

## Login

```
POST /api/auth/login/
{ "username": "rania", "password": "a-strong-passw0rd!" }
```

`200`:

```json
{ "token": "9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b" }
```

Invalid credentials — wrong password **or** a username that doesn't exist — both return
the same `401`:

```json
{ "error": "Invalid credentials." }
```

The two cases are indistinguishable on purpose (same status, same body); nothing here
confirms whether a username exists.

---

## Save / unsave a campsite

Both require `Authorization: Token <token>`.

```
POST /api/saved-campsites/42/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

- `201` — saved.
- `200` — was already saved; no duplicate row is created (`(user, campsite)` is unique).
- `404` — no campsite with that id.
- `401` — missing or invalid token.

```
DELETE /api/saved-campsites/42/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

- `204` — unsaved.
- `404` — no campsite with that id, or it wasn't saved by this user.
- `401` — missing or invalid token.

---

## Not included yet

No endpoint lists a user's saved campsites (`GET /api/saved-campsites/`) — TM05-16's
acceptance criteria only call for saving and unsaving. Add it when a frontend view
actually needs the list.
