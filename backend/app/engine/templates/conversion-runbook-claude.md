# Conversion runbook — ${repository}, ${branch} (Claude Code)

> Written by `python -m app.engine.convert prepare` from `backend/app/engine/templates/conversion-runbook-claude.md`.
> Do not edit it: change the template or the inputs, and prepare again.

Worktree `${worktree}`, branch `${branch}`, from baseline `${base}`. Prepared with ${platform}. Engine: **Claude Code**.

## 1. What the worktree gives Claude Code

| File | What it is |
|---|---|
| `${instructions}` | The instructions for this conversion: the plan (the work items in order), the rules and the scope. Loaded when Claude Code starts. |
| `.claude/skills/<work item>/SKILL.md` | One skill per work item: what to change, where, and when it is done. |
| `.claude/agents/*.md` | Three helpers adapted from Anthropic's `code-modernization` plugin, in that plugin's own form (subagents). |
| `${settings}` | The guardrails Claude Code enforces, not only states: no `git push`, no history rewriting${settings_scope}. |
| `.claude/conversion/` | The assessment addendum and the decision sheet the instructions point to, and the inputs manifest. |
${own_claude_md}
## 2. Start Claude Code in the worktree

Start it **in the worktree's own folder**, never in the registered checkout or a folder above the worktree: Claude Code
reads its project settings (the guardrails) only from the folder it starts in.

```powershell
cd "${worktree}"
claude
```

Check that `git branch --show-current` (ask Claude Code, or run it yourself) shows `${branch}`. Then send this message
exactly as written. Do not add to it or reword it:

```text
${opening}
```

## 3. Standard replies

| If Claude Code asks | Reply |
|---|---|
| To run a build or a test command | Allow it **once** (`Yes`). |
| To edit a file in the worktree | Allow it **once**, or switch to accepting edits for this session (Shift+Tab). |
| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |
| For a value it does not have (host name, time zone, path) | `Do not invent it. Read it from configuration by name and continue.` |
| To choose between options | `Continue with your recommended option.` |
| Whether to continue after a pause | `Continue.` |

Never choose "Yes, and don't ask again" for a command: in a git worktree Claude Code saves that answer in the
registered checkout's `.claude/settings.local.json`, outside this conversion. Anything else: decide for yourself, and
note what you sent.

## 4. A stuck command

If a command has run ${stuck_minutes} minutes with no output, press **Esc** to interrupt Claude Code, then send
`That command did not finish. Run it again, or continue without it and say so.`

## 5. When Claude Code stops

If it stops without its done report (the four results from the opening message), send `Continue.`

## 6. When Claude Code reports done

Check that its report gives all four results from the opening message (build, tests, configuration files, start),
each with the command it ran, and that it committed each work item on its own. If a result is missing, send
`Report done only after every check in my first message, each with the command you ran and its result.`

Then send `Commit all remaining changes on the current branch.` and wait until it has. This must print nothing:

```powershell
git -C "${worktree}" status --porcelain
```

## 7. Verify

From the platform repository:

```powershell
cd backend; .venv\Scripts\Activate.ps1
${verify_command}
```

It writes `VERIFICATION.md` and prints the verdict. The verifier is independent of the agent. Nothing the agent
reported counts as evidence.

To start again after fixing an instruction, run `${prepare_command}`. If this conversion has not been run, its inputs
are refreshed in place. Otherwise it prepares the next conversion, with its own worktree and runbook.
${scope_section}