# Conversion runbook — ${repository}, ${branch}

> Written by `python -m app.engine.convert prepare` from `backend/app/engine/templates/conversion-runbook*.md`.
> Do not edit it: change the templates or the inputs, and prepare again.

Worktree `${worktree}`, branch `${branch}`, from baseline `${base}`. Prepared with ${platform}.

The conversion is prepared for both assistants: GitHub Copilot (section A) and Claude Code (section B). Use whichever
is installed on this machine, and follow only its section. The solution this conversion builds and tests is
`${solution_path}`.
${scope_section}${not_converted_section}
