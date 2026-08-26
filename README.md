<p align="center">
  <img alt="Red Scribble" src="template.svg" width="480">
</p>

# Red Scribble

<p align="center">
  <a href="https://boweiliu.github.io/open-in-minds/?git_url=https://github.com/MINDS_TEMPLATE_REPO_URL"><img alt="Open in Minds" height="64" src="https://img.shields.io/badge/Open%20in%20Minds-D8D1C0?style=for-the-badge"></a>
</p>

Didn't work? Create a Minds workspace and paste this to your agent:
` /use-template https://github.com/MINDS_TEMPLATE_REPO_URL`

## Why you care

Scribble, type, or speak UI feedback directly on any app in your workspace; it routes to your chat agent as one batched, rendered card per send.

Describing a UI problem in words is slow and lossy. "The heading is too big, no,
the one above the second card" takes three sentences and still lands wrong.

Red Scribble lets you point instead. Draw on the thing. Circle it, cross it out,
scrawl a note beside it, or just say what you want out loud. What you marked --
with a screenshot, the exact spot, and the element underneath -- arrives in your
agent's chat as one tidy card, and the agent gets on with it. Marks vanish as
they are dealt with, so what is left on screen is what is still outstanding.

## How to use it

1. Ask any chat to **turn on Red Scribble** for an app (there is a skill for
   it: `enable-red-scribble`). It adds one line to that app's page and points
   feedback at that chat.
2. Open the app. A **red circle** sits in the lower-right corner.
3. **Click it.** The page stops responding to clicks -- now you are annotating.
   Draw anywhere. **Double-click** for a typed note. **Double-click and hold** to
   speak one.
4. **Click the circle again** to hand the page back. Your marks hide but are kept.
5. **Press and hold the circle** for the menu: choose which chat receives the
   feedback, flip on **Live** if you want it sent automatically, or press **Send
   Pending Scribbles**.

Everything you gathered arrives in that chat as one card. Try it on the included
**Scribble Box** page first -- it is there to be scribbled on.

## Ideas for making it yours

- **Put it on your own apps.** The opt-in is two lines: call
  `register_jinja_helper(app)` once, and drop `{{ red_scribble_tag() }}` into
  your page's `<head>`. That is the whole contract.
- **Use Live mode for a tight loop.** Marks auto-send a couple of seconds after
  you make them, and the agent is told to move fast and not polish -- good for
  pushing a layout around, bad for anything you want kept.
- **Change what a mark means.** The agent-side playbook is a plain-English skill
  (`red-scribble-feedback`) -- teach it that a circle means "make this bigger",
  or that a cross means "delete this", and it will follow you.
- **Scribble on someone else's app.** Anything served in your workspace can take
  the opt-in line, not just apps you wrote.

## What this is

This repository is a published **minds template**: a clean, bootable
snapshot of what a mind built, ready to adapt into your own. It is NOT the
generic workspace template -- it is this specific project.

[`template.md`](template.md) is the full manifest -- what it is, how it
works, what it needs to run, and what to adapt -- with the
machine-readable half (recipe, requirements, and the environment it needs
installed) in [`template.toml`](template.toml).
