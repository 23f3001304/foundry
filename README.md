![Foundry](assets/readme-banner.png)

# Foundry

A business's team asks for work in the chat they already use, by text or voice note. Agents in [Switch](https://github.com/sandbox-quantum/switch) rooms draft a brief, make the deck and the graphic, and check each other's work. A person approves the brief and signs off the result before anything is delivered.

The same setup also turns a messy note from the field into a clean report, and shows the person signing it exactly which words changed and which document backs each change.

Built for Flip the Switch, Track 01 (Best Business Workflow). Lalten Cafe, Shilagate Homes, Morpankh Systems, Kasauti Capital Partners, Bhorvela Studio, Phatakha Pop and Ambaryug Teas are fictional, and so is everything in their folders, including every figure.

## What sets it apart

- **One setup across chat platforms.** A single Switch template creates the rooms, agents and documents, and names the chat platform as a setting. Foundry's code talks to Switch, not to a platform.
- **A separate agent checks the work.** Claude writes and makes, and `foundry-reviewer` checks the result against the brief and the brand kit. It runs on Claude now, the same vendor as the makers, so those runs are not a check by another vendor. An earlier run through delivery had Codex, on an OpenAI model, in that seat, and the seat can still be set to another vendor.
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
| The IT firm scene with scripted people, on Nov 5, 2026: request, brief card with who owes what, each Team Lead asked in their own room, answers, a reason, a status question, one reminder, one due card with the reason and the silence, Go without, and a deck with the figures and their printed sources | Run live on Mattermost with real agents and real models, from a git worktree against a running stack, not a fresh clone. The team's messages are scripted. What Foundry said back and the decks are real. The first run's request said "the client", so its deck left the name to be supplied. A later run on Nov 5, 2026 played the wording that names Harsingar Stores, which is made up, and the brief and the deck both use the name. That run played a copy of the scene with only the room names changed, through delivery, and played its last two steps, the routine card, by hand |
| The IT firm's final card, sign-off and delivery | Run live on Mattermost on Nov 5, 2026, with `foundry-reviewer` on Claude, the same vendor as the makers, so **this is not a check by another vendor**. It sent the deck back with two notes, passed the fix, and the deck was delivered 11 m 10 s after the request, with inputs due at 8 minutes. What the reviewer says with a pass now goes on the final card, except a card in a client's own room, which leaves those words off. That part is tested in code and not run live. In the first run, on Codex, the usage limit ran out, the review never passed and nothing was delivered. This scene has not been run through delivery with a reviewer from another vendor |
| Other cards in the first run: Ask for changes with typed notes, a typed `A19 yes`, a typed `yes` in a card's thread, Already told the asker, Ask again, Ask someone else and its follow-up, a passed-on answer, a stuck card from a maker's `WORK_BLOCKED` | Run live on Mattermost |
| Cards reached in the later run: Can't today and Already told the asker on a reminder, the asker's Already told card and They didn't, Keep on a note and Leave out on another | Run live on Mattermost by hand, on extra jobs and notes that are not in the scene file. A kept note is in the report marked "kept after a check", and the left-out note is not in it |
| A flagged number's chain | Run live on a delivered deck, with the flag posted to the dashboard from a script, for the figure 41 and for a quoted reason. It shows who answered, the file that used it, the reviewer's pass with its words, the sign-off and the delivery |
| Signing in to the dashboard with the stack's admin login through `{switch_email}` | Run live from a script, in the later run. Posting that login to `/login` gave a redirect to `/`, and the overview and jobs pages showed the business, as "Demo It Firm" from its folder name. The dashboard now uses the name in the brand kit, Morpankh Systems, which tests cover and no live run has shown yet. It has not been opened in a browser |
| The IT firm's routine cards at the set times | Run live on Mattermost by hand, not by the scene player: "Show what needs me" and "Approve everything clean" both pressed, a typed `yes` told to use the buttons, and the report posted. That run had one room's items on each routine card. A routine card now holds all of a business's rooms, which tests cover and no live run has been through yet |
| The investment firm scene (Kasauti Capital Partners, made-up figures), on Nov 5, 2026: request, brief card with five inputs owed, each Office Head asked in their own room, four figures typed and one file sent, a final card naming one figure as far from the others, review, sign-off and delivery | Run live on Mattermost with real agents and real models, from a git worktree against a running stack, not a fresh clone. The offices' messages and file are scripted. A later run on the fixed code went from the request to delivery in 3 min 15 s with nothing typed but the scripted lines, and a third, with a change asked for on the final card, took 3 min 59 s. The reviewer was `foundry-reviewer` on Claude, the same vendor as the makers, so **this is not a check by another vendor**. The first run needed help: the makers' tool servers timed out connecting (30 s) while other test suites were running on the machine, the run's operator restarted the two makers by hand and pressed Approve on the stuck card, which the scene does not do, and the brief agent's quote of the kit had fooled the scene's wait for the final card's line. A later run with nothing else going on did not time out, so load looks likely, but that was not proven. The six rooms were made one by one from `demo_seed.py`'s own list, because running it would also have made the marketing agency's, so **`demo_seed.py` as a whole was not run for this**. Each problem is fixed or written up in "Good to know" |
| The investment deck: the maker finding `sources/quarterly_aum.csv`, working each office's growth out with `calculate` by office and by quarter, totalling Office C's file, and drawing both charts by code | Run live. Every figure on slides 2 to 5 carried a source line, the growth figures were 18.62, 15.3, 17.22, 14.81 and 24.47, and Office C's total was 4,730. The first deck was sent back by the reviewer with real notes, a table heading cut in two and the first slide's line run on in the title. Both were faults in the deck tool, now fixed, and the second deck passed. A maker that remembered an earlier job in its session kept to its old way until it was told to use the new subtitle option, so a note was typed on the final card in the third run, and then it did. The kit's own line telling a maker to use the subtitle has **not been tried with a fresh maker session**. The slides were drawn and looked at on a machine without the brand fonts, so a reader who has them may see the table fit differently |
| A file sent as an answer: Office Head C's CSV | Run live. The post had the file's name as its words and the file as its only attachment. The desk kept it in the inputs folder under `office-head-c-office-c-q2-fy27.csv`, answered "I saved" 4 seconds later, and the makers' tools opened it by name from the same `FOUNDRY_INPUTS_DIR` |
| The jump line: Office E's 19,800 against 6,420, 5,180 and 7,050, with Office C's file left out of the check | Run live in three runs. The reader kept each typed figure as a bare number, and the final card said office-head-e's answer is far from the others given for this measure, and named no one else. The check was never shown a figure with a unit after it by a real reader, because "digits only" in the pack's measure kept the units out |
| Chains of flagged figures from the investment deck | Flags posted to the dashboard's route by a script that signed in with the stack's admin login, not clicked in a browser, for 19,800, 4,730, 15.3 and Office C's file answer. Each shows who answered or what code worked out and from which rows, the reviewer's words, the sign-off and the delivery. The chain for 4,730 first left out who sent the file, which is fixed and was checked in the second run |
| The number check on finished work | Run by script on six real decks, with no false alarm on a deck made by the same code. The final cards of the later run had no "No source found" line, which fits, and doesn't show the check ran on them. On the investment firm's first run it did fire live, on a period label, which was a false alarm. It is fixed by skipping a period label such as Q1 FY26 by its shape, as a date is skipped, so a wrong quarter name on a slide is not flagged by this check, and the reviewer still reads the slides. On the agency's first run it fired live on a deck headline in capitals, "14 NOVEMBER GOES BANG", also a false alarm and fixed. It has not caught a wrong number on a real deck |
| Confidence on a real model, 20 made-up notes, half garbled | Run on Nov 5, 2026, through the desk's own two steps. All 10 garbled notes came back as a question, and none of the clean, so the question is what stops a garbled note. After the one reply tried, "I don't know, put it in as I said it", low confidence on the report caught 7 of 10 garbled and marked 0 of 10 clean, so clean-up keeps its confidence. A reply that sounds surer has not been measured. An earlier 10 of 10 scored the questions, which the desk never reads. The reader of replies caught 3 of 10, so it lost its confidence |
| One client's fact asked for from another client's job | Run live, when every client's makers shared one folder. Asked plainly, the maker said "not available". Told to open decks already made, it read the other client's deck in the shared folder, and left the fact out by its own choice. Nothing stopped it reading. Since then each agency client is given agents of its own, in a folder of its own. That was run live on Nov 5, 2026, in a worktree against the running stack, with the agents on Claude. Phatakha's makers' own tool servers, started from the `.mcp.json` the set-up wrote, were given Ambaryug's brand folder, folders, pictures and job token in 25 calls over MCP. Every call that should be refused was, in the tool's own words, and no file was made. The desk's rule for the files a maker names, run with the live settings on the real delivered files, took each client's own files and refused the other's in 8 of 8 cases. Through the real request path, Marketing Manager B asked for Phatakha's poster and copy by path, and the brief agent left them out of the brief, and left them out again after the approver typed that it was cleared, so no maker was ever asked for them. **Not shown:** a maker told directly to open the other client's deck. Switch passes an order to an agent only from its owner's linked account, so the scripted people got a refusal and the stack's admin account got no reply. A maker's own file reading is still not confined |
| The marketing agency scene: Bhorvela Studio's Account Director and two clients, Phatakha Pop and Ambaryug Teas, each asking for a full campaign set (deck, poster, social posts at 1080x1080 and 1080x1920, written copy) at once, each with agents of its own | Run live on Mattermost on Nov 5, 2026, with real agents and real models, from a git worktree against a running stack, not a fresh clone. The brief agent, makers and reviewer were all on Claude, so **this is not a check by another vendor**. Both clients asked before either was answered, and each had a brief agent, makers and reviewer of its own. The people's lines are scripted. The first run needed help: on a busy machine every one of the four makers' tool servers timed out connecting (30 s), each maker said so in a `WORK_BLOCKED`, a person pressed Approve on the stuck card and the same session asked again and failed again, so a person stopped and started the four makers in Switch's agent management and pressed Approve again. The reviewer then sent both sets back with notes the fixed deck and graphic layouts cannot do (a paper background, the logo's place, a separate date line), a maker of each client sent `WORK_BLOCKED` (Ambaryug's graphic maker, and Phatakha's graphic and deck makers), and the approver typed in each studio room `revise:` to accept the layouts and drop those notes. Both sets then passed, were signed off and were delivered, Ambaryug's at 06:57 and Phatakha's at 06:59, 16 min 25 s after the first request, of which about 6 min were the connection failure. The two sets look and read differently (Phatakha's red and yellow, with MANGO BANG in capitals, and Ambaryug's green and cream, in sentences). Neither set's deck or copy holds a word of the other client's, and the copy of each says no pictures were drawn. Each client's room held only "Being made." and its own delivery. A second request in Ambaryug's room, a one-slide deck, passed through the same makers' sessions in 52 s from approval to the sign-off card. Phatakha's sign-off card listed "No source found for 14" for a date in a capitals headline, which was a false alarm and is fixed. Poster text sometimes breaks a date across two lines, and the portrait post has an empty lower half, which the reviewer noted and the fixed layouts cannot change |
| Pictures drawn by the Vertex image model inside a campaign set (`FOUNDRY_IMAGES=on`) | **Not run.** The tool is tested against a stand-in for Google's server only, and no real picture was drawn |
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
| `foundry-deck` | Claude, with the `build_deck` and `write_copy` tools | Makes on-brand slides and a branded PDF of written copy |
| `foundry-visual` | Claude, with the `render_graphic` tool | Makes on-brand graphics |
| `foundry-reviewer` | Set by `FOUNDRY_REVIEWER_PROVIDER`. Claude in the recent runs, and Codex in the earlier run by another vendor. OpenCode works too | Checks the work against the brief and the brand kit |

Each agency client made from now on has its own set of these four, named with its own ending, such as `foundry-deck-phatakha`, each in its own folder. That includes Lalten Cafe's and Green Valley's rooms on a fresh stack, because the rule that one client's work stays out of another's is not only for the demos. **Rooms already in your `.env` have no ending, so they keep the shared agents until their rooms are made again,** and the desk says so in its log at start. An internal company or department shares one set across its rooms. When `FOUNDRY_IMAGES=on`, both makers also get a `generate_image` tool.

## Features and the Switch pieces behind them

| Feature | Switch piece |
|---|---|
| Rooms, agents and documents for one client from one file | `version: 2` room template, with `from-template-document` |
| Agency or internal room tree from one setting | Template `if:` on `org_mode` |
| An internal department reusing the same agents | Template `filled` and `allow_existing` |
| An agency client with agents of its own | A template param, `agent_suffix`, that ends each agent's name, and a folder named for the agent |
| Reading all chat without being mentioned | Agent event stream with `filter=all` |
| Who may ask and who may answer | Agent addressing policies, then Foundry's own check in `gates.py` |
| Approvals with buttons | Approval cards on an agent session |
| Questions with their answers as choices | Question cards on an agent session |
| Notes and answers on WhatsApp | The open adapter from sandbox-quantum/switch#1166 with our button and list cards, in `integrations/whatsapp` |
| Brand kit and business pack | Room documents, in the inside rooms only |
| Deck, graphic, copy and picture tools | MCP servers in each maker's `.mcp.json` |
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

This makes rooms for both fictional clients, one internal department to show the other room tree, the four rooms of Morpankh Systems, the fictional IT firm, the six rooms of Kasauti Capital Partners, the fictional investment firm, and the rooms of the marketing agency's two clients, Phatakha Pop and Ambaryug Teas. Each agency client is given agents of its own. The seed also writes each maker's `.mcp.json` and saves the room ids in `.env`.

Set the reviewer before this step, because a reviewer's provider is fixed when it is made and each agency client gets a new one. For now put `FOUNDRY_REVIEWER_PROVIDER=claude` in `.env` and leave `FOUNDRY_REVIEWER_MODEL` empty, because Codex's usage has run out until Dec 4. Without it a new reviewer starts on the template's default and the seed says so.

Picture drawing is off by default. If you want it, set `FOUNDRY_IMAGES=on` and `GOOGLE_CLOUD_PROJECT` in `.env` and sign in with `gcloud auth application-default login` before this step. Everything in this README runs without it. To switch it on or off after the rooms exist, run `uv run --env-file .env python tools/setup_makers.py <agents folder> -<client> <brand folder>` once for each agency client, such as `-phatakha` with the full path of `brands/demo-agency-client-a`. For the shared makers, run `tools/setup_makers.py <agents folder>` with nothing after it. The agents folder is the agent controller's `workspaces_dir`, such as `~/.switch/agents/127.0.0.1-8000`.

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

Kasauti Capital Partners is a fictional global investment firm, and every figure in it is made up. An Analyst Lead asks for a quarterly review deck, and Office Heads A to E each owe their office's assets under management. Four answer by chat, and Office Head C sends a file last. Office Head E's figure is made to jump, to more than three times its last quarter's and far from the other offices, and the desk's check for a figure far from its peers names it on the final card. The makers are told to work the deck's charts out with the data tools, from the answers, the file and `brands/demo-investment-firm/sources/quarterly_aum.csv`, so each figure traces to its calculation and its file, and a figure from a sent file to whoever sent it. **The offices' messages and file are scripted. Everything Foundry says back, and the deck, comes from the real desk, real agents and real models. Its reports are internal summaries of made-up numbers, never advice.**

The rooms come from step 4. Make the scripted people and what they said before the scene, as for the IT firm. The same refusal of any stack that isn't on this machine applies.

```bash
uv run --env-file .env python scripts/demo_people.py ensure investment_firm
uv run --env-file .env python scripts/seed_history.py investment_firm
```

Set `FOUNDRY_QUIET_SECONDS=8` in `.env`. The file Office Head C sends is `scripts/scenes/data/office-c-q2-fy27.csv`. The desk keeps it in `FOUNDRY_INPUTS_DIR`, and the makers' data tools open it from there, so the desk and the tools must mean the same folder. `tools/setup_makers.py` writes that folder into each maker's `.mcp.json` as a full path, so run the desk and the room set-up from this folder with the same `.env`, or give `FOUNDRY_INPUTS_DIR` as a full path. Restart the desk, then play the scene from another terminal.

```bash
uv run --env-file .env python scripts/demo_people.py play investment_firm
```

The inputs are due 15 minutes in and the deck 60 minutes in. The scene needs a reviewer that can run, or it stops at the review. The brief agent reads the room's earlier messages, so a second play in the same rooms gets a brief that says it repeats the earlier request. Use fresh rooms before recording. See "What has actually been run" for how far it got.

### 9. Play the marketing agency demo

Bhorvela Studio is a fictional marketing agency with two fictional clients. Phatakha Pop is a loud fizzy drinks brand, and Ambaryug Teas is a quiet heritage tea house. A Marketing Manager at each asks for a full campaign set: a deck, a poster, social posts at 1080x1080 and 1080x1920, and written copy. Each client's kit leads its set, so the two are meant to come out looking and sounding different, and in the one live run they did. The agency's Account Director approves each brief and each finished set inside the studio rooms, and is a member of each client's review room too, because a long reply of the reviewer's is cut short on the sign-off card and the whole of it is there. The clients see nothing of any of it. **The people's messages are scripted. Everything Foundry says back, and every file, comes from the real desk, real agents and real models.** **This scene has been run live once, on Nov 5, 2026, with every agent on Claude, from a worktree against a running stack and not a fresh clone, and the run needed a person's help twice: the makers' tool servers timed out connecting and were restarted, and the reviewers' notes asked for layouts the tools cannot make. No picture was drawn, and a maker told directly to reach the other client's files was not tried.** See "What has actually been run" for exactly how far it got.

What this demo shows about clients:

- **Each client has agents of its own.** `foundry-deck-phatakha` and `foundry-deck-ambaryug` are different agents in different folders. A client's tools write only in that maker's own folder, show a picture only from it or the client's own brand folder, and open only that client's jobs and brand folder. The desk takes a file only from that client's makers' folders. A maker, reviewer or brief agent from one client is ignored in the other's rooms.
- **A client only learns the stage.** Asked where its work is, it is told "being made" or "being checked", with no name of anyone inside and no who-owes list. Who-owes-what runs in internal mode only.
- **Each client is its own bucket.** The desk picks the bucket from the room, and nothing a model sends can name one. Two clients' files and log entries never mix in a lookup.
- **Clients never sign in to the dashboard.** The packs list only the agency's own login, acting as the Account Director.
- **Pictures are off by default.** With `FOUNDRY_IMAGES` off, the set is still complete, and its written copy has a "Pictures" section that says no pictures were drawn. With `FOUNDRY_IMAGES=on`, the makers may draw at most two pictures with `generate_image`, which calls the same Vertex model as `tools/gen_assets.py`. **Those pictures are AI-generated, and the files say so.** Google's policy bars passing generated content off as made only by people.

Before the seed in step 4 makes these two clients' rooms, set `FOUNDRY_REVIEWER_PROVIDER=claude` and leave `FOUNDRY_REVIEWER_MODEL` empty in `.env`. Each client gets a reviewer of its own, and a reviewer's provider can't be changed once it is made. Then make the scripted people and play the scene. In `.env`, set `FOUNDRY_QUIET_SECONDS=8` first, and restart the desk after the seed so it follows the new rooms.

```bash
uv run --env-file .env python scripts/demo_people.py ensure agency
uv run --env-file .env python scripts/demo_people.py play agency
```

Then open the files each client was given and read them. Phatakha Pop's set should name Mango Masala and never Ambaryug, and Ambaryug Teas' set should name the First Flush Reserve and never Phatakha.

### Good to know

- **A maker that says its services failed to connect:** its session says `CONNECT_TIMEOUT`, meaning the deck, data and log tool servers did not answer within 30 seconds. In our run other test suites were running on the machine, and a later run with nothing else going on did not time out, so load looks likely, but that was not proven. Pressing Approve on the stuck card asks again in the same session, which keeps the failed connection. Restart that maker from Switch's agent management (stop it and start it) first, then press Approve.
- **A reviewer can ask for what the fixed layouts can't do.** The deck and graphic tools have fixed layouts, so a review note such as a different background, the logo's place or a separate date line makes the maker send `WORK_BLOCKED`, and the stuck card says the layout has to change or the approver accept it. In the agency run, typing `revise:` in the studio room, to accept the layouts and drop those notes, got both sets passed on the next review. Approve on those cards, which asks again with the same notes, was not tried.
- **Agents made earlier keep the instructions they were made with.** Switch reuses an existing agent as it is, so on a stack made before a template change the makers have the old instructions, and what they know of the data tools comes from the tool descriptions and the desk's messages. The investment run was on agents made on Nov 4.
- **Fonts:** a `.pptx` can't carry its fonts, so a machine without them shows a substitute. Install the files in `brands/<brand>/fonts` where you open the decks.
- **Reviewer:** Codex uses your machine's login, and Switch copies that login into its session folder under `~/.local/state/switch`. It also takes the reasoning effort from your own `~/.codex/config.toml`. At `xhigh`, the first review took 13 minutes and the second took 4. The agent controller looks for `codex` on PATH, and the desktop app's copy isn't on it, so install the CLI or add the app's folder to PATH before starting the controller. To change the reviewer, set `FOUNDRY_REVIEWER_PROVIDER` and `FOUNDRY_REVIEWER_MODEL` in `.env` before creating the rooms, because an existing `foundry-reviewer` is reused as it is. An agent's provider is fixed when it is registered, so each agency client's own reviewer takes whatever those two say when that client's rooms are made. Codex needs an empty model. Leaving the provider empty uses OpenCode's free model. That free tier has a usage limit, and the terminal can keep working after Switch-hosted OpenCode is refused. When that happens the room shows no error. The reviewer sits on "Working" until the 30-minute timeout, then a stuck card asks a person, so unchecked work never passes. OpenCode's own log says `Free usage limit reached`. Codex has a usage limit too. When it runs out, the reviewer posts the limit's message in the review room, and the desk still waits for the timeout and the stuck card. Claude works too, but then a vendor is checking its own work.
- **Approver:** whoever asks approves their own job. To name someone for one business, set `approver` in quotes in `brands/<brand>/pack.md`, or use `FOUNDRY_APPROVER` for every business that doesn't set its own. The value is a Switch sender id, `@switch-mattermost-<bridge id>-<username>:localhost`. Once that person has sent a request, it's in the `requester` column of `foundry-jobs.db`. With a wrong id, nobody can answer the card.
- **Voice:** set `SARVAM_API_KEY`. Voice notes over 30 seconds get a request to resend or type, which is the limit of Sarvam's REST route. Sarvam charges per call.
- **Classifier:** with no `ANTHROPIC_API_KEY`, Foundry uses this machine's Claude Code login.
- **Old databases:** the job and buffer files aren't migrated between versions. Delete `foundry-*.db` after pulling changes.
- **WhatsApp:** optional, and it changes Switch's code in your own deployment. See [integrations/whatsapp](integrations/whatsapp/README.md).
- **A fresh Switch stack** gives clean channel names. Deleting a room leaves its Mattermost channel behind, and a new room with that name gets a suffix.
- **The reviewer's words stay off a client's card.** A client signing in their own room signs without them, because they can name agents and people the client never sees. So if the reviewer asks for a check, it is missed unless someone inside acts on it. The words stay in the review room, and an approver who signs inside reads them on the card, up to 500 characters. This is tested in code and not run live.
- **Agency clients have their own makers, and an internal business's rooms share one folder.** An internal company or department is one business, so its rooms share one set of agents with one working folder. Agency clients do not: each is given agents of its own, in a folder of its own, because in our live check, when the makers were shared, a maker told to open decks already made read another client's deck and left the fact out by its own choice. Nothing in the code stopped it reading. Now a client's own maker tools write only in that maker's folder, read a picture only from it or the client's brand folder, and open only that client's jobs, and the desk takes a file only from that client's makers' folders. That confines the tools and the desk. It does not confine an agent's own access to the machine's files, which still reach any folder, and its agents are only told that other clients' folders are not theirs. The desk goes by the name of the folder a file is in, so it cannot tell a real maker's folder from another folder of the same name. The tool and desk confinement was run live on Nov 5, 2026, as the first table above says, and the agent's own access was not tried, so don't put real clients' confidential work on this setup as it stands. Switch itself lets any agent list every room, in all clients' businesses, and an agent of the same owner can remove another agent from a room. Reading a room's messages needs membership by Switch's own rule, and that was not seen refused here, because the desk is a member of every room, so it was the desk, not a maker, that was run against these operations.

## Tests

```bash
uv run pytest
```

## Art and credits

Team sprites, stickers, the fictional businesses' logos and photos were generated with Gemini on Vertex AI and then cut to a pixel grid or to size in code, as `tools/gen_assets.py` shows. Foundry's own logo, wordmark and banner were drawn in code, with the wordmark's letters in Archivo Black under the SIL Open Font License, and the banner shows the generated team sprites. They are AI-generated, not hand-drawn, and show original characters and fictional businesses. Brand stickers are recoloured from those sprites in code, and the hard hat and cup are drawn in code. The fonts are open fonts, with their licences beside them in each brand's `fonts` folder.

The dashboard's large abstract forms were generated with Gemini on Vertex AI, and `tools/gen_assets.py` holds the prompts, turns the black around them transparent and re-tints them to one duotone. They are AI-generated, not hand-drawn. The characters that react on its pages are those same generated team sprites and Smith's poses, plus a waving Smith generated the same way, and `tools/make_sprites.py` builds their sprite sheets from those pictures in code. The small icons, the page grid and the charts are drawn in SVG, and the title font is Manrope, an open font with its licence beside it in `src/foundry/dashboard/static/fonts`.

The Kasauti Capital Partners logo is not generated. `tools/draw_kasauti_logo.py` draws it in code, in the two colours of the firm's kit, and its fonts are copies of the open fonts the other brands use.

The marketing agency's three logos and the two clients' pictures are not AI-generated. They are original flat art drawn in code with Pillow, as `tools/draw_agency_art.py` shows, and drawing again gives the same files. Pictures that `generate_image` makes when `FOUNDRY_IMAGES=on` are AI-generated by the same Gemini model on Vertex AI, and each file and its record say so. The agency's fonts are DejaVu Sans Bold, Source Serif Pro, Source Sans Pro and Manrope, with their licences beside them.

Speech comes from [Sarvam](https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe): [Saaras](https://docs.sarvam.ai/api/getting-started/models/saaras) to read and Bulbul to speak.

The WhatsApp adapter is Prakhar Gupta's open pull request to Switch, [sandbox-quantum/switch#1166](https://github.com/sandbox-quantum/switch/pull/1166). We built on it and added reply buttons and lists for Switch's request cards. `integrations/whatsapp` holds their commits under their name, our commits on top, and Switch's licence and notice. It changes Switch's core code in a local deployment, and it needs a Meta app and a public address to run for real.
