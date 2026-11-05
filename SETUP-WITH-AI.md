# Set up Foundry with your AI agent

For a person: open Claude Code, Codex, Gemini CLI or another agent that can run commands in this folder, and paste this:

> Follow SETUP-WITH-AI.md to set up Foundry on my machine.

The rest of this file is for the agent.

## Rules

- Never ask the person for a token, key or password in chat, and never type one yourself. They enter those in the dashboard's Settings page, or in `.env`.
- Never print `.env` or Switch's `.env`, and never read values out of them. Setup writes generated logins there, and nobody needs to see them.
- Don't run `--reset` or `--yes` unless the person asks for it. Ask before using a port setup says is taken.
- Don't create accounts or bots for the person. They do that in the chat app, and you walk them through it.
- Say what failed in plain words, using what the command printed. Don't work around a check.

## Steps

On Windows, use `powershell -ExecutionPolicy Bypass -File .\setup.ps1` wherever this says `./setup.sh`, with the same flags.

1. Ask whether they want to look first or run the real thing.
   - To look: `./setup.sh --try`. It needs only uv, uses made-up data and sends nothing anywhere. Give them the address it prints, and skip to the end.
   - For the real thing: `./setup.sh`.
2. If it says something is missing, tell them all of it with where to get it, then help them install it and run it again. Running it again is safe.
3. Check it with `./setup.sh --status`.
4. Give them the dashboard address setup printed, and tell them to open **Settings**. Nobody signs in, because it answers only on this machine.
5. Walk them through the rest in Settings:
   - **Connect a chat app.** Read them the steps on the page for Telegram, Slack or Mattermost. Setup already connects a local Mattermost, so that one needs nothing.
   - **Models and keys.** A key is optional if the `claude` CLI is signed in. If it isn't, tell them to run `claude` themselves and sign in.
   - **New project.** One for each company. It needs a folder under `brands/` with a `kit.md` in it. Copy the shape of an existing folder there, using what they tell you about the company, and let them check it.
6. To finish, have them send a request in the chat app and watch it appear on the dashboard's Jobs page.

## If they want to stop

`./setup.sh --stop` stops what setup started. `./setup.sh --reset` removes only what setup made, and asks first.
