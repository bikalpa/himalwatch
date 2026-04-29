# Working Style — Bikal (bikalpa@gmail.com)

## Deploy Philosophy
- Wants **auto-deploy on push to main** so he can edit from anywhere and see
  changes live without manual steps
- Cost-conscious: asked to remove Cloudflare Pages once Vercel was set up to avoid
  paying for two hosting platforms simultaneously
- Prefers the simplest possible deploy path (no build steps for the dashboard)

## Feedback Style
- Points out issues concisely with a numbered list (e.g. "5 issues: (1)… (2)…")
- Prefers confirmations via screenshot or snapshot rather than just trust-me answers
- Accepts incremental fixes — OK with "this will self-resolve when pipeline data arrives"
- Comfortable saying "that's fine" and moving on once root cause is understood

## UI Testing
- Expects end-to-end smoke tests after changes: load → map → nav all views →
  detail panel → dark/light toggle → logo-to-home
- Uses Claude Preview tool (local Python HTTP server on port 3000) for visual testing
- Launch config at `himalwatch/.claude/launch.json`

## What Not To Do
- Don't deploy to the wrong platform (nearly used Cloudflare Pages when CLAUDE.md
  says Vercel — user caught it and redirected)
- Don't ask about optional parameters; infer from context
- Don't leave broken links in the UI (e.g. dead logo click, invisible text from
  missing `color:inherit` on button elements)
