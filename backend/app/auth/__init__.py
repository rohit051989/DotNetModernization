"""Identity and ownership (docs/VDI-SETUP.md, "Users and sign-in"; 04-FRONTEND-SPEC.md, "Sign-in and roles").

Several developers each run their own platform, backend and frontend on their own machine, against one database.
- machine: the Windows account this process runs under and the machine's hostname.
- passwords: salted scrypt hashes; a password is never stored or logged.
- actor: who is acting in this request or command, carried in a context variable.
- service: users, sign-in, sessions, and the registered user a command-line tool acts as.
- policy: which role, or which repository owner, may take each action (enforced for every API call).
- activity: who did what, from which machine.
- versions: an edit made from a stale copy of a shared record is refused.

Matching the Windows account and the machine deters shared credentials. It is not a hard security boundary: the
platform runs on the user's own machine, which the user controls.
"""
