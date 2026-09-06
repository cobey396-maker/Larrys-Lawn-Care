"""Admin sign in / sign out."""

from .. import db, security
from ..routing import HTTPError, Response, Router
from ..validation import Validator

router = Router()


@router.post("/api/admin/login")
def login(request):
    validator = Validator(request.json_body())
    validator.text("username", required=True, max_length=80)
    validator.text("password", required=True, max_length=200)
    data = validator.done()

    user, session = security.authenticate(data["username"], data["password"], request.client_ip)
    return Response.json({
        "token": session["token"],
        "expires_at": session["expires_at"],
        "user": {"id": user["id"], "username": user["username"]},
    })


@router.post("/api/admin/logout")
@security.require_admin
def logout(request):
    security.destroy_session(request.header("Authorization", "")[7:].strip())
    return Response.no_content()


@router.get("/api/admin/me")
@security.require_admin
def me(request):
    return Response.json({"user": request.user})


@router.post("/api/admin/password")
@security.require_admin
def change_password(request):
    validator = Validator(request.json_body())
    validator.text("current_password", required=True, max_length=200)
    validator.text("new_password", required=True, max_length=200)
    data = validator.done()

    row = db.query_one("SELECT password_hash FROM admin_users WHERE id = ?",
                       (request.user["id"],))
    if not security.verify_password(data["current_password"], row["password_hash"]):
        raise HTTPError(401, "Current password is wrong.", code="invalid_credentials")
    if len(data["new_password"]) < 8:
        raise HTTPError(422, "Choose a longer password.",
                        fields={"new_password": "At least 8 characters."})

    security.set_password(request.user["username"], data["new_password"])
    # Every other session is now stale; drop them all and hand back a fresh one.
    db.execute("DELETE FROM sessions WHERE user_id = ?", (request.user["id"],))
    session = security.create_session(request.user["id"], request.client_ip)
    return Response.json({"token": session["token"], "expires_at": session["expires_at"]})
