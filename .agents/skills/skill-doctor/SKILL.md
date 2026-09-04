---
name: skill-doctor
description: >-
  Grades agent skills by scoring agent conversations against efficiency and code-quality rubrics, then drafts concrete skill edits and a shareable report. Use when the user wants their agent setup graded from real conversation history, or asks which of their installed skills are actually working.
---

# skill-doctor

Grade the user's agent setup by scoring agent conversations, then propose concrete skill edits and render one shareable report artifact.

## Step 0: Start the run

Use the `ask_question` tool to ask the user:
**"Which conversations should I grade?"**
1. **Current conversation** (Recommended)
2. **Specific conversation ID** (If chosen, ask the user to provide the ID in a follow-up)

If the user wants to evaluate specific skills, ask which ones. Otherwise, evaluate all skills in the current workspace (`.agents/skills/`).

## Step 1: Collect

Identify the conversation transcripts to analyze.
Antigravity conversation transcripts are stored at:
`<appDataDir>/brain/<conversation-id>/.system_generated/logs/transcript.jsonl`

For the current conversation, your conversation ID is available in your configuration.
Read the `transcript.jsonl` using the `view_file` or `grep_search` tools to understand the actions taken, tools used, and code changed.

## Step 2: Score the transcript

Scoring is based on efficiency and code quality. Review the rubrics provided in this skill's `scorers/` directory:
- [efficiency.md](./scorers/efficiency.md)
- [code-quality.md](./scorers/code-quality.md)

Read the transcript and judge it against both rubrics. For each rubric, record the label, numeric score, and a 1–3 sentence reason citing specifics from the transcript. If there are no code changes, record `insufficient_evidence` for code quality.

## Step 3: Draft skill edits

Based on the scoring, propose improvements to the workspace skills.
1. Check the existing skills in `.agents/skills/`.
2. Draft skill edits to address observed waste or defects. Focus on trigger descriptions, missing preflight checks, or missing steps.
3. For new skills, draft a complete `SKILL.md`.

Do not modify the user's real skill files directly without their approval. Instead, include the proposed changes in your report.

## Step 4: Write report and render

Create an artifact named `skill_doctor_report.md` in your artifact directory.
Set `ArtifactMetadata.UserFacing = true` and `ArtifactMetadata.RequestFeedback = false`.

The report should include:
- **Title**: Agent Skill Report
- **Target Conversation**: Link to the conversation using `[Conversation](conversation://<conversation-id>)`
- **Scores**: Efficiency and Code Quality scores (0.0 to 1.0), and an overall grade.
- **Top Findings**: The 3 most impactful, specific patterns.
- **Suggestions**: Concrete skill changes with before/after diffs or new skill proposals.

## Step 5: Output

Present the findings to the user and ask if they would like you to apply the suggested skill edits.
