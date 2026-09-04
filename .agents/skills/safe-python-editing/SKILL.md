---
name: safe-python-editing
description: >-
  Rules for making python edits safely, verifying imports, and keeping the workspace clean.
---

# Safe Python Editing

When editing Python code in this workspace, strictly follow these rules:

1. **Verify Before Using**: Never assume a function, method, or config variable exists. Always use `grep_search` to find how a variable is currently used in the codebase before importing or referencing it.
2. **No Workspace Clutter**: If you need to create a temporary script (e.g. to run a regex replacement or check a snippet), you MUST save it in your artifact scratch directory: `<appDataDir>/brain/<conversation-id>/scratch/`. DO NOT create `test.py` or `fix.py` in the project root.
3. **Syntax Checking**: After modifying any `.py` file, immediately run `python3 -m py_compile <file>` to catch indentation or syntax errors before the user restarts the app.
