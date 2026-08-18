# The Daily Loop — How It Runs From Your Phone

The program runs itself through three cloud routines plus your own chats in the
Claude mobile app. The shared memory is a Google Doc called **`TRADER PREP LOG`**
— the routines write to it, and any mobile chat can read it. That doc, not this
repo, is what makes the loop continuous (the cloud routines cannot read this
repo; Drive is the bridge).

## The cycle

| When | What happens | Where |
|---|---|---|
| **07:00** | Morning coach reads the whole log (yesterday's debrief included), works out which week/day you're on and what carries over, writes a detailed `## PLAN — date` section into the doc, pushes a short notification | automatic |
| **daytime** | You open the Claude mobile app and work through the plan with it — task by task | you |
| **21:00** | Evening check-in reads today's PLAN + your calendar, writes a `## DEBRIEF — date` with a `CARRY INTO TOMORROW:` line, pushes the check-in | automatic |
| **23:00** | Last call — pings only if `PREP DONE` is still missing from your calendar; silent if you marked it | automatic |
| **next 07:00** | Tomorrow's plan is built from that debrief — the loop closes | automatic |

## The phrases (this is the whole interface)

Open the Claude mobile app and say:

- **`coach me through today`** — it reads `TRADER PREP LOG` in Drive, finds
  today's PLAN, and walks you through it task by task.
- **`quiz me on drill set B`** — live mental-math drilling, spoken answers.
- **`log my day`** — tell it what you actually did; ask it to append a
  `## SELF-REPORT — <date>` section to `TRADER PREP LOG`. Tonight's check-in and
  tomorrow's plan both read that.
- **`explain <topic> from my syllabus`** — Week-N teaching on demand.
- **`I'm stuck on <X>`** — but see the Iron Rule below.

If a fresh chat seems not to know the context, say: *"Read the Google Doc
`TRADER PREP LOG` first."* That is the only setup a new chat ever needs.

## Marking the day done

Add a Google Calendar event titled **`PREP DONE`** on the day. That is what the
21:00 and 23:00 routines check; marking it silences the last call. For partial
days, add an event titled `PREP: <what you did>` (e.g. `PREP: blotter + drill
only`) — the evening routine reads those too and carries the rest forward
instead of losing it.

## The Iron Rule still applies on mobile

The mobile coach may **explain, quiz, review, and unstick you in words**. It may
**never write your build-track or kata code** — that is the whole point of the
coding-readiness track (`08`). If you ask for code, the correct answer is a
hint, a rubber-duck question, or a review of what you already wrote. Ask for
review at the **end of the week**, not mid-task.

## If something breaks

- **No notification:** the routines are cloud-side and fire regardless of any
  device being on; check the Claude mobile app is logged into
  `taha.dazine@gmail.com` with notifications allowed. Phone off = delivered when
  it reconnects.
- **Log doc missing or plan not written:** the morning routine creates
  `TRADER PREP LOG` if absent; you can also just ask a mobile chat to create it
  with that exact name.
- **Routine management:** https://claude.ai/code/routines (morning
  `trig_0117fFodbwd5JSAg15YuLU1i`, evening `trig_01EwBdSoV2DESJ5JR9QiwbGu`,
  last call `trig_015VivSwKZ6AyG9ibPQ1Yhwy`). Deletion is only possible there.

## Where the repo still matters

Your actual work lives here, on your PC: the blotter files
(`docs/trader-prep/blotter/YYYY-MM.md`), the hand-written build code, the kata
log. Drive holds the *plan and progress narrative*; the repo holds the *output*.
Reopen the Claude Code CLI when you want deep work on the repo itself — that is
the only place with real file access.
