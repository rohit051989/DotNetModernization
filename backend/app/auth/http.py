"""The guard every API call passes through (a dependency of the whole app, app.main):

1. a signed-in session: the HttpOnly cookie, live (not signed out, not idle past SESSION_IDLE_MINUTES), made on
   this machine; else 401 SIGNED_OUT. Only signing in, the machine's own identity and the health check are open;
2. a password reset by an admin must be replaced first: until then only changing it and signing out are allowed;
3. the policy (app.auth.policy): who may make this call; else 403 NOT_ALLOWED, saying why;
4. the person, set as the current actor for the work the call does;
5. once the call has succeeded, a change is recorded: who, from which machine, which action, on what.

An async dependency, so the actor it sets is the context the route runs in, even a synchronous route on the
thread pool. Its database work is a few small queries on a session of its own.
"""
from fastapi import Request

from app.auth import activity, machine, policy, service
from app.auth import actor as actors
from app.db import SessionLocal
from app.errors import error

# Open without a session: signing in, what this machine and account are (the sign-in page shows them), the health
# check, and the API's own documentation.
OPEN = ("/api/auth/sign-in", "/api/auth/machine", "/api/health")
OPEN_PREFIXES = ("/docs", "/redoc", "/openapi.json")
# Allowed while a reset password still has to be replaced.
PASSWORD_CHANGE = ("/api/auth/password", "/api/auth/sign-out", "/api/auth/me")


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


async def guard(request: Request):
    path = request.url.path
    if path in OPEN or path.startswith(OPEN_PREFIXES) or not path.startswith("/api"):
        yield
        return
    host = machine.hostname()
    method = request.method.upper()
    with SessionLocal() as db:
        found = service.resolve(db, request.cookies.get(service.COOKIE), host=host)
        db.commit()
        if found is None:
            raise error(401, "Sign in first: there is no signed-in session, or it ended (signed out, or unused for "
                             f"{service.settings.session_idle_minutes} minutes).", code="SIGNED_OUT")
        user, _session = found
        person = actors.of(user, host)
        if user.must_change_password and path not in PASSWORD_CHANGE:
            raise error(403, "Your password was set by an admin: choose a new one first.", code="PASSWORD_CHANGE_REQUIRED")
        if why := policy.refusal(db, person, method, _route_path(request), dict(request.path_params)):
            raise error(403, why, code="NOT_ALLOWED")
    token = actors.set_current(person)
    about, about_token = activity.collect()
    request.state.actor = person
    try:
        yield
        if method not in policy.READ_METHODS and path not in PASSWORD_CHANGE:
            route = request.scope.get("route")
            subject_type, subject_id = about.get("subject") or activity.subject_of(dict(request.path_params))
            with SessionLocal() as db:
                activity.record(db, getattr(route, "name", None) or path, subject_type, subject_id,
                                getattr(route, "summary", None) or f"{method} {path}", actor=person)
                db.commit()
    finally:
        activity.release(about_token)
        actors.reset(token)
