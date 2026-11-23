## A. GitHub Copilot
${unsafe}
### A1. Open the solution in Visual Studio

Open `${solution_path}` in Visual Studio: this conversion's own solution, in the worktree, never the registered
checkout. Check that the Git branch shown is `${branch}`.

### A2. Open the modernization agent and send the first message

In Solution Explorer, right-click the solution and choose **Modernize**: the GitHub Copilot modernization agent opens in
a **new** Copilot chat thread. Send this message exactly as written. Do not add to it or reword it:

```text
${opening}
```

### A3. Standard replies

| If the agent asks | Reply |
|---|---|
| Target framework | `${target}` |
| Branch, Git strategy, commits | `Work on the current branch and do not create another branch. Commit each instruction on its own once it builds, naming it in the commit message.` |
| Automatic or guided flow | `Guided.` |
| Upgrade options | `Use the answers in .github/platform-inputs/decision-sheet.md. Where it gives none, continue with your recommended option.` |
| Whether to plan, or to execute the plan | `Proceed.` |
| To choose between options | `Continue with your recommended option.` |
| For a credential, a secret, a sign-in, an installation or a change outside the repository | `No. Continue without it.` |
| For a value it does not have (host name, time zone, path) | `Do not invent it. Read it from configuration by name and continue.` |
| Whether to continue after a pause | `Continue.` |

Anything else: decide for yourself, and note what you sent.

### A4. A stuck terminal

If a terminal shows `>>` (PowerShell is waiting for the rest of a command), or a command has run ${stuck_minutes} minutes
with no output, press **Ctrl+C** in that terminal. If Ctrl+C does not clear `>>`, close the Copilot terminal: it
reopens and retries the command. If the agent then stops, send `Continue.`

### A5. When the agent stops or reports done

If the agent stops without its done report (the four results from the first message), send `Continue.` When it reports
done, check that its report gives all four results (build, tests, configuration files, start), each with the command
it ran. If one is missing, send
`Report done only after every check in my first message, each with the command you ran and its result.`

Then send `Commit all remaining changes on the current branch.` and wait until it has. This must print nothing:

```powershell
git -C "${worktree}" status --porcelain
```

### A6. Verify

On the repository's Conversion tab, press **Verify** and choose **GitHub Copilot** as the assistant that did the
conversion. From the command line instead:

```powershell
cd backend; .venv\Scripts\Activate.ps1
${verify_command} --assistant github-copilot
```

It writes `VERIFICATION.md`, naming the assistant, and gives the verdict. The verifier is independent of the agent:
nothing the agent reported counts as evidence.
