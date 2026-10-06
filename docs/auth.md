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
| `/api/auth/logout/` | `POST` | Yes | `204`, token revoked |
| `/api/auth/me/` | `GET` | Yes | `200` with the token's owner |
| `/api/auth/me/` | `DELETE` | Yes | `204`, account deleted |
| `/api/saved-campsites/` | `GET` | Yes | `200` with this user's saved campsites |
| `/api/saved-campsites/<source_id>/` | `POST` | Yes | `201` (or `200` if already saved) |
| `/api/saved-campsites/<source_id>/` | `DELETE` | Yes | `204` |

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
{ "non_field_errors": ["This password is too common."] }
```

The key is `non_field_errors`, not `password`. Validation runs in the serializer's
object-level `validate()` rather than in a per-field method, because
`UserAttributeSimilarityValidator` has to compare the password against the username and
email in the same payload — it cannot see them from inside a `validate_password` field
method. DRF files object-level errors under `non_field_errors`, so that is where these
land. (This page previously documented `{"password": [...]}`, which the server has never
returned.)

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

## Log out

```
POST /api/auth/logout/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

`204`, no body. The token row is **deleted**, not flagged — tokens carry no expiry and no
refresh flow, so the row's existence is the session and removing it is what actually
revokes access. Every later request with that token gets `401`, including a second logout.

Logging in again issues a fresh token; the old string never works again. Clearing the
token client-side without calling this endpoint leaves a working credential on the server,
so sign-out must go through here.

- `204` — signed out.
- `401` — missing, invalid, or already-revoked token.

Only the presented token is revoked. Other accounts are untouched.

---

## Current user

Who does this token belong to — for restoring a session on page load, when the client has
a stored token but no user.

```
GET /api/auth/me/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

`200`:

```json
{ "username": "rania", "email": "rania@example.com" }
```

Same shape as the registration response, so a client has one idea of what an account looks
like. The user's database id is deliberately not included — no endpoint here exposes an
internal row id.

- `401` — missing or invalid token.

---

## Delete account (TM05-70)

Deletes the account the token belongs to.

```
DELETE /api/auth/me/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

`204`, no body. In one transaction, the server deletes:
- **the user**,
- **their auth token**, so every later request with it gets `401`, including a second delete,
- **their saved campsites**.

The campsites themselves are shared reference data and stay.

- `204` — account deleted.
- `401` — missing or invalid token. Nothing is deleted.

The endpoint acts only on the token's owner and takes no id, so no request can delete or
change another account, token or saved campsite. There is no confirmation step or grace
period, and deletion cannot be undone. The client should ask "are you sure?" before
calling it, then drop its stored token.

**How the related rows go.** Every foreign key to the user is `on_delete=CASCADE`:
`authtoken.Token.user`, `accounts.SavedCampsite.user` and Django's admin log. Group and
permission memberships are many-to-many rows Django removes along with the user. So
`user.delete()` removes it all, with no explicit deletes. `test_every_foreign_key_to_the_user_cascades`
walks the user model's relations and fails if a future model points at the user without
`CASCADE`. The delete endpoint then has to handle that model explicitly.

---

## List saved campsites

```
GET /api/saved-campsites/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

`200` with a JSON array, **newest save first**:

```json
[
  {
    "id": "campsite/73996",
    "name": "Marcy Dam",
    "site_type": "lean_to",
    "reservable": null,
    "capacity": null,
    "latitude": 44.1,
    "longitude": -74.05,
    "saved_at": "2026-09-28T14:02:11.482913Z"
  }
]
```

An empty list (`[]`) when nothing is saved — not a `404`. Scoped to the token's owner, so
one user can never see another's saves; there is no id in the URL to tamper with.

- `401` — missing or invalid token.

### Why this shape

**`id` is the `source_id`** — the same string the map API puts in each GeoJSON Feature's
`id` ([api.md](api.md#feature-id)) and the same string you `POST` and `DELETE` to save and
unsave. All three being identical is the point: the frontend can fetch this list once and
mark which pins on the map are already saved, with no per-site lookup and no id
translation anywhere.

**Flat JSON, not GeoJSON.** A campsite is a Point, so returning full geometry would cost a
handful of bytes — this is not a size decision. It is that the two things a client does
with this list are render a row and call `flyTo(longitude, latitude)`, and neither wants to
unwrap `geometry.coordinates`. The map layers stay GeoJSON because MapLibre consumes them
directly; this list is not fed to MapLibre.

**Properties mirror the map API's campsite layer** (`name`, `site_type`, `reservable`,
`capacity`), so a saved entry and a map feature describe a campsite the same way.

`reservable` and `capacity` are `null` when the source didn't say. Null is not `false` and
not `0` — "unknown" and "not reservable" are different answers, and the serializer keeps
them apart.

---

## Save / unsave a campsite

Both require `Authorization: Token <token>`.

The id in the path is the campsite's **`source_id`** -- the same string the map API puts in
each GeoJSON Feature's `id`, documented in [api.md](api.md#feature-id). Take it from the
feature you are looking at and send it back unchanged. It is *not* the database primary
key, which is never exposed.

It usually contains a slash (`campsite/73996`), so build the URL by appending the raw
value; do not assume it is a single path segment and do not percent-encode the slash.

```
POST /api/saved-campsites/campsite/73996/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

- `201` — saved.
- `200` — was already saved; no duplicate row is created (`(user, campsite)` is unique).
- `404` — no campsite with that id.
- `401` — missing or invalid token.

```
DELETE /api/saved-campsites/campsite/73996/
Authorization: Token 9a4f2c1e8b3d4a6f9c0e1b2d3a4f5c6d7e8f9a0b
```

- `204` — unsaved.
- `404` — no campsite with that id, or it wasn't saved by this user.
- `401` — missing or invalid token.

---

## Not included yet

No pagination on the saved list. A user's saves are inherently few — tens, not thousands —
and the endpoint returns a bare array so a client can render it directly. If that ever
stops being true, paginating changes the response from an array to an object with a
`results` key, which is a breaking change; better to make it deliberately later than to
carry the wrapper now.

No token expiry or refresh. Tokens live until logout deletes them. Worth revisiting before
anything is deployed publicly, but it is a change to the auth model rather than a gap in
these endpoints.
