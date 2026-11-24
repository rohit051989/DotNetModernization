## B. Claude Code
${unsafe}
Claude Code works in the worktree's folder; no solution is opened for it. Its instructions, `${instructions}`, tell it
to build and test `${solution}`.

| File | What it is |
|---|---|
| `${instructions}` | The instructions for this conversion: the plan (the work items in order), the rules and the scope. Loaded when Claude Code starts. |
| `.claude/skills/<work item>/SKILL.md` | One skill per work item: what to change, where, and when it is done. |
| `.claude/agents/*.md` | Three helpers adapted from Anthropic's `code-modernization` plugin, in that plugin's own form (subagents). |
| `${settings}` | The guardrails Claude Code enforces, not only states: no `git push`, no history rewriting${settings_scope}. |
| `.claude/conversion/` | The assessment addendum and the decision sheet the instructions point to, and the inputs manifest. |
${own_claude_md}
### B1. Start Claude Code at the worktree's root

Start it **in the worktree's root folder**, `${worktree}`, never in the registered checkout or a folder above the
worktree: Claude Code reads its project settings (the guardrails) only from the folder it starts in. Either open a
terminal there and start it:

```powershell
cd "${worktree}"
claude
```

or open the folder `${worktree}` in VS Code (**File > Open Folder**) and open the **Claude Code** panel of the Claude
Code extension. Check that `git branch --show-current` (ask Claude Code, or run it yourself) shows `${branch}`.

### B2. Send the first message

Send this message exactly as written. Do not add to it or reword it:

```text
${opening}
```
${design_questions}
### B3. Permission prompts

| If Claude Code asks | Reply |
|---|---|
| To run a build or a test command | Allow it **once** (`Yes`). |
| To edit a file in the worktree | Allow it **once**, or switch to accepting edits for this session (Shift+Tab). |
| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |
| For a value it does not have (host name, time zone, path) | `Do not invent it. Read it from configuration by name and continue.` |
| To choose between options (other than its design questions) | `Continue with your recommended option.` |
| Whether to continue after a pause | `Continue.` |

Never choose "Yes, and don't ask again" for a command: in a git worktree Claude Code saves that answer in the
registered checkout's `.claude/settings.local.json`, outside this conversion. If a command has run ${stuck_minutes} minutes
with no output, press **Esc** and send
`That command did not finish. Run it again, or continue without it and say so.` Anything else: decide for yourself,
and note what you sent.

### B4. An interrupted session

If Claude Code stopped (the terminal or VS Code was closed, the machine restarted), continue the same conversation from
the same folder:

```powershell
cd "${worktree}"
claude --continue
```

(`claude --resume` lists the earlier conversations to choose from; in VS Code, open the conversation again from the
Claude Code panel's history.) Then send `Continue.` If it stops without its done report (the four results from the first
message), send `Continue.`

### B5. Check that each work item was committed

When Claude Code reports done, check that its report gives all four results (build, tests, configuration files, start),
each with the command it ran. If one is missing, send
`Report done only after every check in my first message, each with the command you ran and its result.`

Each work item is committed on its own, naming it. This lists the commits since the inputs; there is one for each work
item:

```powershell
git -C "${worktree}" log --oneline ${head}..HEAD
```

${work_items}

If one is missing, send `Commit each work item that is not committed yet on its own, naming it.` Then send
`Commit all remaining changes on the current branch.` and wait until it has. This must print nothing:

```powershell
git -C "${worktree}" status --porcelain
```

### B6. Verify

On the repository's Conversion tab, press **Verify** and choose **Claude Code** as the assistant that did the
conversion. From the command line instead:

```powershell
cd backend; .venv\Scripts\Activate.ps1
${verify_command} --assistant claude-code
```

It writes `VERIFICATION.md`, naming the assistant, and gives the verdict. The verifier is independent of the agent:
nothing the agent reported counts as evidence.
