# PIM-Pipeline-III — instructions for Claude

**Entry point.** At the start of every session, before doing anything else, read:

1. This file.
2. `README.md` — what the project is, what is built, and where every document lives.
3. `.claude/root-CLAUDE.md` — Tony's global working rules. It lives on his PC only and is
   deliberately not in git (the GitHub repo is public).

@.claude/root-CLAUDE.md

**Handoff notes.** A handoff note carries only work started in another session that continues
in this one. It is not the entry point. Read it after the README when one exists, and delete it
once that work is done.

## Working rules for this project (Tony, 2026-11-18)

- Claude makes every commit and every push, through the GitHub API, always. Never give Tony
  command-line steps to run.
- Push token: `.ct-gh-token` in this repo's root. Git-ignored, never committed, never printed.
  After every push, confirm through the GitHub REST API that GitHub's `main` equals local HEAD.
- Do the work instead of handing steps back. Before acting, say in one short line what you are
  doing, then do it. No "shall I?" questions.
- `castletronics_hub` is a different project (CT Hub). This is PIM development: never use the hub
  folder for PIM work or for the PIM token.
- The GitHub repo is public. Never commit vendor files, builds (`var/`), tokens,
  `.claude/root-CLAUDE.md`, or dealer pricing.
- Verify against the actual output files, not just the code.

## Machine notes

- When Claude reaches this repo from a cloud session, it is mounted at `$HOME/mnt/PIM-Pipeline-III`
  in a Linux shell on Tony's PC (Python 3.10). The package needs Python 3.11+, so install the
  dependencies directly and run with `PYTHONPATH=.`; run builds with `PIM_VAR_DIR=$HOME/pimvar3`.
- `git commit` there needs delete permission on this folder (git's lock file).
- The window (`PIM.bat`, port 8766) runs on Tony's Windows Python and must be restarted after
  any change to `pim/ui/` code.
