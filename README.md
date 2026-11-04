![Foundry](assets/readme-banner.png)

# Foundry

A business's team asks for work in the chat they already use, by text or voice note. Agents in [Switch](https://github.com/sandbox-quantum/switch) rooms draft a brief, make the deck and the graphic, and check each other's work. A person approves the brief and signs off the result before anything is delivered.

The same setup also turns a messy note from the field into a clean report, and shows the person signing it exactly which words changed and which document backs each change.

Built for Flip the Switch, Track 01 (Best Business Workflow). Lalten Cafe, Shilagate Homes, Morpankh Systems and Kasauti Capital Partners are fictional, and so is everything in their folders, including every figure.

## What sets it apart

- **One setup across chat platforms.** A single Switch template creates the rooms, agents and documents, and names the chat platform as a setting. Foundry's code talks to Switch, not to a platform.
- **Agents from different vendors check each other.** Claude writes and makes. Codex, on an OpenAI model, checks the work, and Claude isn't among the template's defaults for that seat.
- **Voice notes in Indian languages.** Sarvam's Saaras model reads Hinglish as spoken, a plain "haan" counts as approval, and whoever sends a voice note hears questions, the report and the final reply in their language. Cards stay in English.
- **Code holds the gates, not prompts.** Makers aren't called until a brief is approved, only the approver's answer counts, and nothing is delivered before sign-off. A named approver signs off inside, so the client sees nothing until then. Someone approving their own job sees the brief and the files on the way.
- **A report can't quietly invent things.** The model proposes each change with its evidence. Code drops any change whose evidence isn't really in the named document, does all the date maths itself, and flags numbers it can't trace. It flags names too, unless one opens a sentence, where a capital says nothing.

## What has actually been run

| What | Status |
|---|---|
| Request, brief, approval, deck and poster, review, sign-off, delivery | Run live on Mattermost with real agents |
| Review notes staying out of the outside room | Checked in that run |
| Note clean-up: question, answer, sign-off, report in both rooms | Run live on Mattermost |
| A question with its answers on a card, when the sources list them | Run live on Mattermost by typing the answer, and on WhatsApp against the stand-in by pressing |
| The builder's example note and three harder ones | Run on a real model, correct on Sonnet in two runs |
| Stuck job, 30-minute timeout, restart with a person's go-ahead | Run live on Mattermost |
| These steps from a fresh clone on a wiped Switch stack | Run by the author up to the makers and through the note clean-up. Not yet run by a teammate |
| Reviewer on another vendor | Run live on Mattermost through delivery with Codex on `gpt-5.6-terra`. It sent one slide back with a note, passed the fix, and was shown the images. This used the Codex copy from the desktop app, version 0.146.0-alpha.9.2, not an `npm` install. An earlier OpenCode review also worked, until its free usage limit ran out |
| The IT firm scene with scripted people, on Nov 5, 2026: request, brief card with who owes what, each Team Lead asked in their own room, answers, a reason, a status question, one reminder, one due card with the reason and the silence, Go without, and a deck with the figures and their printed sources | Run live on Mattermost with real agents and real models, from a git worktree against a running stack, not a fresh clone. The team's messages are scripted. What Foundry said back and the deck are real. In that run the request said "the client", so the deck left the name to be supplied. The scene now names Harsingar Stores, which is made up, and that wording has not been played live |
| The IT firm's final card, sign-off and delivery | **Not run.** Codex's usage limit ran out in this run, so the reviewer posted the limit's message and never passed anything. The job stayed in review until the stuck card, and trying again failed the same way. No review was faked, so the deck was never delivered |
| Other cards in that run: Ask for changes with typed notes, a typed `A19 yes`, a typed `yes` in a card's thread, Already told the asker, Ask again, Ask someone else and its follow-up, a passed-on answer, a stuck card from a maker's `WORK_BLOCKED` | Run live on Mattermost |
| A flagged number's chain | Run on the real log and the real deck by calling `chain_for` from a script. It holds who answered and who used it, and no review or sign-off, because neither ran. The dashboard's flag button is not part of this run |
| The IT firm's routine cards at the set times | Run live on Mattermost by hand, not by the scene player, which had stopped at the review: "Show what needs me" and "Approve everything clean" both pressed, a typed `yes` told to use the buttons, and the report posted. Keep and Leave out were not reached, because no note in the run needed attention |
| The investment firm scene: five Office Heads each owe assets under management, four answer by chat and one by a file, one figure is far from the others, and the deck's charts are to be worked out by code | **Not run live yet.** The firm's kit and pack, the scene, the made-up figures and the tests are in, and the scene's checks of its own figures run in the tests. Nothing here says what Foundry did with them |
| The number check on finished work | Run by script on six real decks, because no final card could open. No false alarm on a deck made by the same code. It has not caught a wrong number on a real deck |
| Confidence on a real model, 20 made-up notes, half garbled | Run on Nov 5, 2026, through the desk's own two steps. All 10 garbled notes came back as a question, and none of the clean, so the question is what stops a garbled note. After the one reply tried, "I don't know, put it in as I said it", low confidence on the report caught 7 of 10 garbled and marked 0 of 10 clean, so clean-up keeps its confidence. A reply that sounds surer has not been measured. An earlier 10 of 10 scored the questions, which the desk never reads. The reader of replies caught 3 of 10, so it lost its confidence |
| One client's fact asked for from another client's job | Run live. Asked plainly, the maker said "not available". Told to open decks already made, it read the other client's deck in the shared folder, and left the fact out by its own choice. Nothing stops it reading, see "The makers share one folder" |
| Voice notes and voice replies | Tested against a fake Sarvam only, no key yet. In the IT firm scene the voice note's words were typed instead, and the scene says so |
| Telegram, and an outside person answering there | Not run, needs a bot token |
| Slack, Discord, Teams | Not run, so not claimed |
| WhatsApp cards: buttons, list, typed answer, sign-off, changes, delivery | Run through a real Switch and the desk against a local stand-in for Meta's API, with made-up credentials. Not run on Meta's real API, which needs a Meta app and a public address |
| WhatsApp voice notes and incoming files | Not run |
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
| `foundry-reviewer` | Codex, or OpenCode if you change the setting | Checks the work against the brief and the brand kit |

## Features and the Switch pieces behind them

| Feature | Switch piece |
|---|---|
| Rooms, agents and documents for one client from one file | `version: 2` room template, with `from-template-document` |
| Agency or internal room tree from one setting | Template `if:` on `org_mode` |
| A second client reusing the same agents | Template `filled` and `allow_existing` |
| Reading all chat without being mentioned | Agent event stream with `filter=all` |
| Who may ask and who may answer | Agent addressing policies, then Foundry's own check in `gates.py` |
| Approvals with buttons | Approval cards on an agent session |
| Questions with their answers as choices | Question cards on an agent session |
| Notes and answers on WhatsApp | The open adapter from sandbox-quantum/switch#1166 with our button and list cards, in `integrations/whatsapp` |
| Brand kit and business pack | Room documents, in the inside rooms only |
| Deck and graphic tools | MCP servers in each maker's `.mcp.json` |
| Sending files and stickers | Room media route |
| Agents on a machine you control | Agent controller, and the `agent_management` flag |
| Keeping clients out of the workrooms | Separate rooms grouped and linked by label, with the desk alone in both |

## Run it

You need Docker, [uv](https://docs.astral.sh/uv/), Node 22.13 or newer with pnpm, a signed-in [Claude Code](https://claude.com/claude-code), and a signed-in [Codex CLI](https://github.com/openai/codex) (`npm install -g @openai/codex`, then `codex login`). Commands use a POSIX shell, such as Git Bash on Windows.

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

Leave this running in its own terminal, one where the `codex` command works:

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

This makes rooms for both fictional clients, one internal department to show the other room tree, the four rooms of Morpankh Systems, the fictional IT firm, and the six rooms of Kasauti Capital Partners, the fictional investment firm. It also writes each maker's `.mcp.json` and saves the room ids in `.env`.

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

### 7. Play the IT firm demo

Morpankh Systems is a fictional IT firm, and its client Harsingar Stores is made up too. A Delivery Manager asks for a release status deck, and three Team Leads each owe the figures for it. Team Lead A answers, Team Lead B says "blocked on QA", and Team Lead C says nothing. **The team's messages are scripted. Everything Foundry says back, and the deck, comes from the real desk, real agents and real models.**

Put Mattermost's admin sign-in and team name in `.env`. They are in Switch's own `.env`. Then make the scripted people and what they said before the scene. The history is marked as seeded in the log. These scripts sign in as the admin and reset the password of anyone with a scripted person's name, so they refuse any `MATTERMOST_URL` or `SWITCH_URL` that isn't on this machine.

```bash
uv run --env-file .env python scripts/demo_people.py ensure it_firm
uv run --env-file .env python scripts/seed_history.py it_firm
```

In `.env`, set `FOUNDRY_QUIET_SECONDS=8`, and set `FOUNDRY_SET_TIMES` to two clock times, 25 and 28 minutes from now. Restart the desk, then play the scene from another terminal. It prints a timeline, and each step waits for what Foundry really does.

```bash
uv run --env-file .env python scripts/demo_people.py play it_firm
```

The inputs are due 8 minutes in. The scene needs a reviewer that can run, or it stops at the review. See "What has actually been run" for how far it got.

To measure whether a model's confidence catches a garbled note once the desk has asked about it and had a reply, run `tools/confidence_test.py` with the same `uv run --env-file .env python`.

### 8. Play the investment firm demo

Kasauti Capital Partners is a fictional global investment firm, and every figure in it is made up. An Analyst Lead asks for a quarterly review deck, and Office Heads A to E each owe their office's assets under management. Four answer by chat, and Office Head C sends a file last. Office Head E's figure is made to jump, to more than three times its last quarter's and far from the other offices, so the desk's check for a figure far from its peers should name it on the final card. The makers are told to work the deck's charts out with the data tools, from the answers, the file and `brands/demo-investment-firm/sources/quarterly_aum.csv`, so each figure should trace to its calculation and its file, and a figure from a sent file to whoever sent it. Whether the deck does that has not been run. **The offices' messages and file are scripted. Everything Foundry says back, and the deck, comes from the real desk, real agents and real models. Its reports are internal summaries of made-up numbers, never advice.**

The rooms come from step 4. Make the scripted people and what they said before the scene, as for the IT firm. The same refusal of any stack that isn't on this machine applies.

```bash
uv run --env-file .env python scripts/demo_people.py ensure investment_firm
uv run --env-file .env python scripts/seed_history.py investment_firm
```

Set `FOUNDRY_QUIET_SECONDS=8` in `.env`. The file Office Head C sends is `scripts/scenes/data/office-c-q2-fy27.csv`. The desk keeps it in `FOUNDRY_INPUTS_DIR`, and the makers' data tools open it from there, so the desk and the tools must mean the same folder. `tools/setup_makers.py` writes that folder into each maker's `.mcp.json` as a full path, so run the desk and the room set-up from this folder with the same `.env`, or give `FOUNDRY_INPUTS_DIR` as a full path. Restart the desk, then play the scene from another terminal.

```bash
uv run --env-file .env python scripts/demo_people.py play investment_firm
```

The inputs are due 15 minutes in and the deck 60 minutes in. The scene needs a reviewer that can run, or it stops at the review. See "What has actually been run" for how far it got.

### Good to know

- **Fonts:** a `.pptx` can't carry its fonts, so a machine without them shows a substitute. Install the files in `brands/<brand>/fonts` where you open the decks.
- **Reviewer:** Codex uses your machine's login, and Switch copies that login into its session folder under `~/.local/state/switch`. It also takes the reasoning effort from your own `~/.codex/config.toml`. At `xhigh`, the first review took 13 minutes and the second took 4. The agent controller looks for `codex` on PATH, and the desktop app's copy isn't on it, so install the CLI or add the app's folder to PATH before starting the controller. To change the reviewer, set `FOUNDRY_REVIEWER_PROVIDER` and `FOUNDRY_REVIEWER_MODEL` in `.env` before creating the rooms, because an existing `foundry-reviewer` is reused as it is. Codex needs an empty model. Leaving the provider empty uses OpenCode's free model. That free tier has a usage limit, and the terminal can keep working after Switch-hosted OpenCode is refused. When that happens the room shows no error. The reviewer sits on "Working" until the 30-minute timeout, then a stuck card asks a person, so unchecked work never passes. OpenCode's own log says `Free usage limit reached`. Codex has a usage limit too. When it runs out, the reviewer posts the limit's message in the review room, and the desk still waits for the timeout and the stuck card. Claude works too, but then a vendor is checking its own work.
- **Approver:** whoever asks approves their own job. To name someone for one business, set `approver` in quotes in `brands/<brand>/pack.md`, or use `FOUNDRY_APPROVER` for every business that doesn't set its own. The value is a Switch sender id, `@switch-mattermost-<bridge id>-<username>:localhost`. Once that person has sent a request, it's in the `requester` column of `foundry-jobs.db`. With a wrong id, nobody can answer the card.
- **Voice:** set `SARVAM_API_KEY`. Voice notes over 30 seconds get a request to resend or type, which is the limit of Sarvam's REST route. Sarvam charges per call.
- **Classifier:** with no `ANTHROPIC_API_KEY`, Foundry uses this machine's Claude Code login.
- **Old databases:** the job and buffer files aren't migrated between versions. Delete `foundry-*.db` after pulling changes.
- **WhatsApp:** optional, and it changes Switch's code in your own deployment. See [integrations/whatsapp](integrations/whatsapp/README.md).
- **A fresh Switch stack** gives clean channel names. Deleting a room leaves its Mattermost channel behind, and a new room with that name gets a suffix.
- **The makers share one folder.** They are one set of agents with one working folder across every client, so any job's maker can open a deck made for another client. In our live check, a maker told to open decks already made read another client's deck and left the fact out by its own choice. Nothing in the code stopped it reading. Don't put real clients' confidential work on this setup as it stands.

## Tests

```bash
uv run pytest
```

## Art and credits

Team sprites, stickers, logos, photos and the banner were generated with Gemini on Vertex AI and then cut to a pixel grid or to size in code, as `tools/gen_assets.py` shows. They are AI-generated, not hand-drawn, and show original characters and fictional businesses. Brand stickers are recoloured from those sprites in code, and the hard hat and cup are drawn in code. The fonts are open fonts, with their licences beside them in each brand's `fonts` folder.

The Kasauti Capital Partners logo is not generated. `tools/draw_kasauti_logo.py` draws it in code, in the two colours of the firm's kit, and its fonts are copies of the open fonts the other brands use.

Speech comes from [Sarvam](https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe): [Saaras](https://docs.sarvam.ai/api/getting-started/models/saaras) to read and Bulbul to speak.

The WhatsApp adapter is Prakhar Gupta's open pull request to Switch, [sandbox-quantum/switch#1166](https://github.com/sandbox-quantum/switch/pull/1166). We built on it and added reply buttons and lists for Switch's request cards. `integrations/whatsapp` holds their commits under their name, our commits on top, and Switch's licence and notice. It changes Switch's core code in a local deployment, and it needs a Meta app and a public address to run for real.
