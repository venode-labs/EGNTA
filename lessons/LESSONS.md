# Egenta lessons

Durable rules Egenta has learnt by watching Claude Code operate. Each lesson is
evidence-backed and traces to the sessions that produced it. A finding is a
hypothesis until it recurs in at least three sessions, then it earns a place
here. Lessons that target the watched agent's rulebook (`~/.claude/CLAUDE.md`)
are proposed through the queue, never written there directly.

## Format

```
### <short title>
- Pattern: what the agent did, across which sessions.
- Evidence: session ids and turn refs.
- Root cause: why it happened.
- Fix: the artifact (script, skill, lesson, training data) and where it landed.
- Status: hypothesis | validated | shipped
```

## Lessons

_None yet. Egenta seeds this as it observes. The first sweep runs once the
daemon is built and the cursor is past the existing transcripts in
`~/clilogs/claude-logs/sessions/`._
