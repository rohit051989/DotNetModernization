"""Who is acting: the signed-in user of an API call, or the registered user a command-line tool acts as. Carried in a
context variable, so ownership checks and the activity record reach it wherever the work happens."""
import contextvars
import uuid
from dataclasses import dataclass

BEFORE_SIGN_IN = "before sign-in"
ADMIN, DEVELOPER = "admin", "developer"
ROLES = (ADMIN, DEVELOPER)


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID | None
    login: str
    name: str
    role: str
    hostname: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN

    def label(self) -> str:
        return f"{self.name} ({self.login})" if self.user_id else self.name


# The platform's own work, outside any person's action: the seed, migrations, a job step. It records as itself.
SYSTEM = Actor(None, "system", "the platform", ADMIN, None)

_current: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("platform_actor", default=None)


def current() -> Actor | None:
    return _current.get()


def set_current(actor: Actor | None) -> contextvars.Token:
    return _current.set(actor)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def of(user, hostname: str | None) -> Actor:
    return Actor(user.id, user.login, user.name, user.role, hostname)
