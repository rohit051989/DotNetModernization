# Conversion runbook — ${repository}, ${branch}

> Written by `python -m app.engine.convert prepare` from `backend/app/engine/templates/conversion-runbook.md`.
> Do not edit it: change the template or the inputs, and prepare again.

Worktree `${worktree}`, branch `${branch}`, from baseline `${base}`. Prepared at platform commit `${platform}`.

## 1. Open the worktree

Open `${worktree}\${solution}` in Visual Studio. Open the worktree, never the registered checkout. Check that the Git
branch shown is `${branch}`. Open a **new** Copilot chat thread.

## 2. Send the opening message

Right-click the solution in Solution Explorer, choose **Modernize**, and send this message exactly as written. Do not
add to it or reword it:

```text
${opening}
```

## 3. Standard replies

| If the agent asks | Reply |
|---|---|
| Target framework | `${target}` |
| Branch, Git strategy, commits | `Work on the current branch and do not create another branch. One commit at the end is fine.` |
| Automatic or guided flow | `Guided.` |
| Upgrade options | `Use the answers in .github/platform-inputs/decision-sheet.md. Where it gives none, continue with your recommended option.` |
| Whether to plan, or to execute the plan | `Proceed.` |
| To choose between options | `Continue with your recommended option.` |
| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |
| For a value it does not have (host name, time zone, path) | `Do not invent it. Read it from configuration by name and continue.` |
| Whether to continue after a pause | `Continue.` |

Anything else: decide for yourself, and note what you sent.

## 4. A stuck terminal

If a terminal shows `>>` (PowerShell is waiting for the rest of a command), or a command has run ${stuck_minutes} minutes
with no output, press **Ctrl+C** in that terminal. If Ctrl+C does not clear `>>`, close the Copilot terminal: it
reopens and retries the command. If the agent then stops, send `Continue.`

## 5. When the agent stops

If the agent stops without its done report (the four results from the opening message), send `Continue.`

## 6. When the agent reports done

Check that its report gives all four results from the opening message (build, tests, configuration files, start),
each with the command it ran. If one is missing, send
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
