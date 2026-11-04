![Foundry](assets/readme-banner.png)

# Foundry

A business's team asks for work in the chat they already use, by text or voice note. Agents in [Switch](https://github.com/sandbox-quantum/switch) rooms draft a brief, make the deck and the graphic, and check each other's work. A person approves the brief and signs off the result, and only then does anything go out.

The same setup also turns a messy note from the field into a clean report, and shows the person signing it exactly which words changed and which document backs each change.

Built for Flip the Switch, Track 01 (Best Business Workflow). Lalten Cafe and Shilagate Homes are fictional, and so is everything in their folders.

## What sets it apart

- **One setup across chat platforms.** A single Switch template creates the rooms, agents and documents, and names the chat platform as a setting. Foundry's code talks to Switch, not to a platform.
- **Agents from different vendors check each other.** Claude writes and makes. The reviewer defaults to a different vendor's model through OpenCode, and Claude isn't among the template's defaults for that seat.
- **Voice notes in Indian languages.** Sarvam's Saaras model reads Hinglish as spoken, a plain "haan" counts as approval, and whoever sends a voice note hears the reply in their language.
- **Code holds the gates, not prompts.** Makers aren't called until a brief is approved, only the approver's answer counts, and nothing reaches the outside room before sign-off.
- **A report can't quietly invent things.** The model proposes each change with its evidence. Code drops any change whose evidence isn't really in the named document, does all the date maths itself, and flags numbers and names it can't trace.

## What has actually been run

| What | Status |
|---|---|
| Request, brief, approval, deck and poster, review, sign-off, delivery | Run live on Mattermost with real agents |
| Review notes staying out of the outside room | Checked in that run |
| Note clean-up: question, answer, sign-off, report in both rooms | Run live on Mattermost |
| The builder's example note and three harder ones | Run on a real model, correct on Sonnet in two runs |
| Stuck job, 30-minute timeout, restart with a person's go-ahead | Run live on Mattermost |
| These steps from a fresh clone on a wiped Switch stack | Run by the author up to the makers and through the note clean-up. Not yet run by a teammate |
| Reviewer on another vendor | Partly. A real OpenCode review with notes worked, then Switch-hosted OpenCode hit its free usage limit. The run through to delivery used Claude as the stand-in reviewer |
| Voice notes and voice replies | Tested against a fake Sarvam only, no key yet |
| Telegram, and an outside person answering there | Not run, needs a bot token |
| Slack, Discord, Teams | Not run, so not claimed |
| WhatsApp | Not built |
| Classifier through an Anthropic API key | Not run. The Claude Code login route has been run |

## How a job moves

```
Outside room           Studio room                 Review room
request or voice note
   |  foundry-desk sorts it, and ordinary chat stays as context
   +------------------> foundry-brief drafts
brief card  <----------+
   |  approver says yes
   +------------------> foundry-deck and foundry-visual make the files
                           +-----------------------> foundry-reviewer checks
                           <--- notes, up to 3 rounds --+
sign-off card, with the files  <------------------------+ passes
   |  approver says yes
final work, and nothing else, posted here
```

A report skips the brief and the makers. The desk writes it from the note, asks the sender if something is unclear, and the approver signs off once.

## The team

| Agent | Runs on | Job |
|---|---|---|
| `foundry-desk` | Foundry's own process | Reads every room, sorts messages, runs approvals, delivers |
| `foundry-brief` | Claude | Turns a request into a one-page brief |
| `foundry-deck` | Claude, with the `build_deck` tool | Makes on-brand slides |
| `foundry-visual` | Claude, with the `render_graphic` tool | Makes on-brand graphics |
| `foundry-reviewer` | OpenCode or Codex | Checks the work against the brief and the brand kit |

## Features and the Switch pieces behind them

| Feature | Switch piece |
|---|---|
| Rooms, agents and documents for one client from one file | `version: 2` room template, with `from-template-document` |
| Agency or internal room tree from one setting | Template `if:` on `org_mode` |
| A second client reusing the same agents | Template `filled` and `allow_existing` |
| Reading all chat without being mentioned | Agent event stream with `filter=all` |
| Who may ask and who may answer | Agent addressing policies, then Foundry's own check in `gates.py` |
| Approvals with buttons | Approval cards on an agent session |
| Brand kit and business pack | Room documents, in the inside rooms only |
| Deck and graphic tools | MCP servers in each maker's `.mcp.json` |
| Sending files and stickers | Room media route |
| Agents on a machine you control | Agent controller, and the `agent_management` flag |
| Keeping clients out of the workrooms | Separate rooms grouped and linked by label, with the desk alone in both |

## Run it

You need Docker, [uv](https://docs.astral.sh/uv/), Node 22.13 or newer with pnpm, a signed-in [Claude Code](https://claude.com/claude-code), and [OpenCode](https://opencode.ai). Commands use a POSIX shell, such as Git Bash on Windows.

### 1. Start Switch

These steps were tested at commit `2d72c57`.

```bash
git clone https://github.com/sandbox-quantum/switch
```

```bash
cd switch && git checkout 2d72c57 && cp .env.example .env && deploy/local/generate-env-secrets.sh .env local
```

Foundry's template needs agent management. In Switch's `.env`, set these two values, using any random string of at least 32 characters for the secret. If another Postgres already uses port 5432, set `POSTGRES_HOST_PORT` too.

```
FEATURE_FLAGS_ENABLED=agent_management
CONTROLLER_TOKEN_SECRET=<random string>
```

```bash
docker compose -f deploy/local/standalone-docker-compose.yml --profile collab --profile gateway --project-directory . up -d
```

The API is on port 8000 and Mattermost on port 8065. Sign in details are in Switch's `.env`: `GATEWAY_ADMIN_EMAIL` and `GATEWAY_ADMIN_PASSWORD` for the API, `MATTERMOST_ADMIN_USER` and `MATTERMOST_ADMIN_PASSWORD` for Mattermost.

### 2. Start the agent controller

This runs the agents on your machine. From `switch/console`:

```bash
pnpm install && pnpm -r --filter './packages/**' run build
```

Get an enrolment code by signing in and asking for one:

```bash
curl -s -c /tmp/switch -H 'Content-Type: application/json' -d '{"email":"<admin email>","password":"<admin password>"}' http://127.0.0.1:8000/gateway/auth/login > /dev/null && curl -s -b /tmp/switch -X POST http://127.0.0.1:8000/gateway/management/enrollment-codes
```

```bash
node packages/agent-controller/dist/cli.mjs enroll --server http://127.0.0.1:8000 --code <code> --data-dir ../controller-data
```

Leave this running in its own terminal:

```bash
node packages/agent-controller/dist/cli.mjs run --data-dir ../controller-data --no-self-update
```

### 3. Set up Foundry

In a new terminal, from this repository:

```bash
cp .env.example .env && uv sync
```

Put the Switch admin email and password in `.env` as `SWITCH_EMAIL` and `SWITCH_PASSWORD`, then register the desk. This saves its id and key in `.env`.

```bash
uv run --env-file .env python tools/register_desk.py
```

### 4. Create the rooms

This makes rooms for both fictional clients, plus one internal department to show the other room tree. It also writes each maker's `.mcp.json` and saves the room ids in `.env`.

```bash
uv run --env-file .env python scripts/demo_seed.py
```

For a client of your own, add a folder under `brands/` and run:

```bash
uv run --env-file .env python tools/create_rooms.py agency <room-name> <brand-folder>
```

### 5. Start the desk

Restart it whenever you add rooms, because it only follows the rooms named in `.env` when it starts.

```bash
uv run --env-file .env python -m foundry
```

### 6. Try it

Sign in to Mattermost at http://127.0.0.1:8065 and open the `lalten` room. After a minute of quiet, or `FOUNDRY_QUIET_SECONDS` if you set it lower, the desk picks this up:

> We need a short deck for our weekend menu launch and one poster to go with it. Kerala filter coffee is the new special, and we open at 7am on Saturday.

Then open the `green-valley` room and try a note from the site:

> palm court pe bhijli wala aaya tha, row 2 ki wiring ho gayi

The contact sheet lists two electricians at Palm Court, so the desk asks which one. Reply with `Electrician A`, and a sign-off card shows the report and the change.

`brands/shilagate-homes/sources/reports.md` has fixed dates. A note that says "the work started 2 days ago" only finds its match when the dates line up, so edit that file to suit the day you try it.

### Good to know

- **Fonts:** a `.pptx` can't carry its fonts, so a machine without them shows a substitute. Install the files in `brands/<brand>/fonts` where you open the decks.
- **Reviewer:** OpenCode's free tier has a usage limit, and the terminal can keep working after Switch-hosted OpenCode is refused. When that happens the room shows no error. The reviewer sits on "Working" until the 30-minute timeout, then a stuck card asks a person, so unchecked work never passes. OpenCode's own log says `Free usage limit reached`. To change the reviewer, set `FOUNDRY_REVIEWER_PROVIDER` and `FOUNDRY_REVIEWER_MODEL` in `.env` before creating the rooms. Codex needs an empty model. Claude works too, but then a vendor is checking its own work.
- **Voice:** set `SARVAM_API_KEY`. Voice notes over 30 seconds get a request to resend or type, which is the limit of Sarvam's REST route. Sarvam charges per call.
- **Classifier:** with no `ANTHROPIC_API_KEY`, Foundry uses this machine's Claude Code login.
- **Old databases:** the job and buffer files aren't migrated between versions. Delete `foundry-*.db` after pulling changes.
- **A fresh Switch stack** gives clean channel names. Deleting a room leaves its Mattermost channel behind, and a new room with that name gets a suffix.

## Tests

```bash
uv run pytest
```

## Art and credits

Team sprites, stickers, logos, photos and the banner were generated with Gemini on Vertex AI and then cut to a pixel grid or to size in code, as `tools/gen_assets.py` shows. They are AI-generated, not hand-drawn, and show original characters and fictional businesses. Brand stickers are recoloured from those sprites in code, and the hard hat and cup are drawn in code. The fonts are open fonts, with their licences beside them in each brand's `fonts` folder.

Speech comes from [Sarvam](https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe): [Saaras](https://docs.sarvam.ai/api/getting-started/models/saaras) to read and Bulbul to speak.

WhatsApp is not in this build. If it's added, the plan is to reuse Prakhar Gupta's open pull request, [sandbox-quantum/switch#1166](https://github.com/sandbox-quantum/switch/pull/1166), rather than write another adapter. That needs a change to Switch's core, and it would be shown on video only, because it needs a Meta app and a public address.
