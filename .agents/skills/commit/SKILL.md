---
name: commit
description: Create a verified git commit from the current repository changes using Conventional Commits 1.0.0. Use when asked to commit, prepare a commit message, or finalize staged work.
---

# Commit

Create a commit that accurately reflects the actual changes in the working tree.

Follow Conventional Commits 1.0.0:
https://www.conventionalcommits.org/en/v1.0.0/

## Inspect the change

Read the repository instructions first.

Then inspect:

```bash
git status
git diff
git diff --staged
```
