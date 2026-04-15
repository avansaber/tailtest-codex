---
name: tailtest-off
description: Pause tailtest automatic test generation for this session.
---

Pause tailtest for this session.

Set `paused: true` in `.tailtest/session.json`. Respond exactly: "tailtest paused. Type /tailtest on to resume."

The Stop hook reads this flag and returns `decision: continue` without queueing files while paused. No other behaviour changes.
