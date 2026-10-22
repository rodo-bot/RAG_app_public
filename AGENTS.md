# Rules for AI assistants working in this repository

The owner does not use Git directly and does not want to learn it. You (the AI) handle all
Git and GitHub work. Follow these rules every time, without being reminded.

## 1. Read first
Before changing anything, read `README.md`, this file, and `CHANGELOG.md`.

## 2. Never commit secrets or site data
Never commit any of the following, in code, config, comments, or commit messages:
- Passwords, API keys, tokens, license keys
- Customer site names, site IP addresses, VPN details, network maps
- PLC/HMI/SCADA project files that contain real site data
- Personal information

Put these in a local `.env` or `secrets/` folder (both are in `.gitignore`) and commit a
`.env.example` with placeholder values instead. If you find a secret already committed, remove
it, tell the owner immediately, and say which credential must be changed.

## 3. Branches: `main` always works
- `main` must always contain a version that runs.
- Do new features, fixes and experiments on a branch named `feature/<short-name>` or `fix/<short-name>`.
- Merge into `main` only after you have actually run the code and confirmed it works.
- If an experiment fails, leave `main` untouched.

## 4. Keep the README current
With every change, update `README.md`:
- **Status** line at the top (see rule 6)
- What the app does, in plain English
- Install and run steps for each OS it supports (Windows / macOS / Linux)

## 5. Keep a plain-English changelog
Add one line per change to `CHANGELOG.md`, newest at the top, under a date heading.
Write it for a non-programmer: what changed and why, not code details.

## 6. Status label
The first line under the README title is exactly one of:
`Status: Working` · `Status: In progress` · `Status: Broken` · `Status: Abandoned`
Update it whenever the truth changes.

## 7. Releases (known-good versions)
When `main` works and the owner wants a version to install elsewhere, create a release tag
`vMAJOR.MINOR` (e.g. `v1.3`) and a GitHub Release with a one-paragraph summary. Installs on
other computers should use a release, not the latest `main`.

## 8. Commits
Small, focused commits with clear messages that describe what changed in plain English.

## 9. Structure
- One app per repository. Throwaway experiments go in the owner's `sandbox` repository.
- Keep source code in `src/`, docs in `docs/`, scripts in `scripts/`.
- List every dependency in the language's standard file (`requirements.txt`, `package.json`, etc.).

## 10. Act, then report
You do not need to ask permission for routine work. When you finish, tell the owner in a few
plain sentences what you changed and what state the app is in.
