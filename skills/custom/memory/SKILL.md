---
name: memory
description: Save session context to a memory file, load previous memory files, or clear context
---

## What this skill does
Manages session memory across opencode sessions. You can save the current context as a markdown file, load a previous memory to restore context, or clear the working context.

## Memory location
Base path: `<repo>\l1-control\opencode\.opencode\memory\` — **统一路径**。无论当前工作区是什么，所有记忆都保存到此路径，不随工作区变化。

**Two save modes:**

| Mode | Path | When |
|---|---|---|
| **Flat** | `<repo>\l1-control\opencode\.opencode\memory\YYYY-MM-DD-HHmm.md` | Default — general session memories |
| **Grouped** | `<repo>\l1-control\opencode\.opencode\memory\<workspace-name>\YYYY-MM-DD-HHmm.md` | User says "save for XXX project" — creates a subfolder for that workspace |
| **Todo (permanent)** | `<repo>\l1-control\opencode\.opencode\memory\TODO.md` | User says "待办", "todo", or asks to write a pending item |

## Todo (permanent)

`TODO.md` is a **permanent, never-expiring** file that stores ONLY pending items + brief pointers to where knowledge lives. It must NOT contain knowledge body itself, and must NEVER be digested/renamed to `.digested.md`.

Format:

```markdown
### [ ] 1. <todo title>
- **事由**：<why it exists, 1 short line>
- **线索**：<which memory file or 05-知识/ page to look in>
- **下一步**：<what's needed to close it>
```

Completion rule: mark `[x]` in place (keep the line as a trail), do NOT delete the item. Prepend new items at the top of the todo list.

**Section maintenance**: When updating TODO.md (user says "更新TODO" or during recall/refresh), move all `[x]` items to a `## 已完成` section at the bottom (separated by `---`), keeping the 待办 section clean. Do NOT re-read files for items already marked done — just relocate them.

---

## Command
The user invokes this skill via natural language. Key trigger phrases:

| What | Say |
|---|---|
| Save memory | "remember", "save memory", "save context", "记一下" |
| Save for a project | "save for <name>", "remember for <name>" |
| Add todo | "写待办", "todo", "记到待办", "加一个待办" — write to TODO.md |
| Load memory | "load memory", "read memory", "recall", "回忆一下" |
| List | "list memories" |
| Clear | "clear context", "reset" |

---

## Save
When the user says "save context", "save memory", "remember", or similar:

1. Determine the save mode:
   - If user mentions a workspace name (e.g., "save for X project"), use **grouped** mode with subfolder `X`
   - Otherwise, use **flat** mode
2. Ensure the directory exists: `mkdir -Force "<repo>\l1-control\opencode\.opencode\memory"` (or `mkdir -Force "<repo>\l1-control\opencode\.opencode\memory\<workspace-name>"` for grouped)
3. Write a memory file at the determined path with this structure:

```markdown
# Memory: <project name>
**Saved at**: <timestamp>
**Directory**: <cwd>
**Branch**: <git branch>

## Context
<Brief summary of what this session is about>

## Key Decisions
- <decision 1>
- <decision 2>

## What Was Done
- <accomplishment 1>
- <accomplishment 2>

## What's Pending
- <pending item 1>
- <pending item 2>

## Notes
<any other important context, file paths, config changes, etc.>
```

4. Confirm the save path to the user (e.g., `Saved: <repo>\l1-control\opencode\.opencode\memory\2026-07-06-1511.md` or `Saved: <repo>\l1-control\opencode\.opencode\memory\MCP\2026-07-06-1511.md`).

---

## Load (auto-select, zero file reads for selection)

When the user says "load memory", "load context", "recall", or similar — **select automatically, do not open files to probe**:

0. **Always read `<repo>\l1-control\opencode\.opencode\memory\TODO.md` first if it exists** — the permanent todo list. Present **only pending items** (above `---` divider); skip the `## 已完成` section. This is the cross-session task source of truth.
1. List remaining `<repo>\l1-control\opencode\.opencode\memory\*.md` **filenames only**, sorted by `LastWriteTime` descending.
2. Skip filenames ending in `.digested.md` — the `.digested` suffix IS the marker (set by vault-digest rename) that content already lives in the vault. No file contents are read during selection.
3. Pick the **first remaining** file (most recent undigested) and read + present its contents — exactly one file read.
4. None left (all digested)? Read the most recent `.digested` file or pull from vault; only then ask the user.
5. Optionally ask whether to delete the loaded file.

---

## Clear
When the user says "clear context", "clear memory", "reset", or similar:

1. **First** ask the user: "Do you want to save the current context before clearing?"
   - If yes, follow the **Save** flow above first.
2. Then inform the user:
   - To clear the agent's context in TUI, use the `/reset` command.
   - To clear in CLI/headless mode, restart opencode.
3. Do NOT attempt to clear context yourself — this is a platform-level operation.

---

## List
When the user says "list memories", "list snapshots", or "lsmem":

1. Recursively list all `.md` files in `<repo>\l1-control\opencode\.opencode\memory\` sorted by date descending with file sizes and paths.
2. Show the count and total size.
3. If there are grouped subdirectories, show the breakdown per workspace.
