# WhatsApp for Foundry

People can send Foundry a note on WhatsApp and answer its question and sign-off cards with buttons, through Meta's official Cloud API.

## Where this comes from

The adapter is Prakhar Gupta's ([Prakharrdev](https://github.com/Prakharrdev)) open pull request to Switch, [sandbox-quantum/switch#1166](https://github.com/sandbox-quantum/switch/pull/1166). The first two commits in `switch-whatsapp.patch` are theirs, unchanged and under their name. The pull request has not been merged into Switch.

Switch is by SandboxAQ, under Apache 2.0 with the Commons Clause. `LICENSE` and `NOTICE` are copied here unchanged and cover this folder. Each Switch file we changed says so on its first line.

## What we added

Switch draws a request card as text. The pull request's adapter sends that text, so a person answers by typing `A1 2`. The last two commits add:

| Card | What the person gets on WhatsApp |
|---|---|
| Up to 3 answers | Reply buttons |
| 4 to 10 answers | A list behind a "Choose an answer" button |
| More than 10 answers | Text only, answered by typing |
| Text over WhatsApp's 1024 limit | The text first, then the buttons in their own message |

Typing `A1 2` still works on every card. A press goes through the same check as any other Switch card, so it counts only on the message that carried it. `test_whatsapp_cards.py` covers this.

On Foundry's side, `tools/connect_whatsapp.py` registers the connection and `tools/link_chat.py` links a chat to a client.

## Set it up

You need your own Meta app and an https address Meta can reach. A person has to create both.

1. In your Switch checkout at commit `2d72c57`, apply the patch:

   ```bash
   git am ../foundry/integrations/whatsapp/switch-whatsapp.patch
   ```

   Change the path to wherever you cloned Foundry.

2. Start a tunnel to port 8000, and set `MESSAGING_PUBLIC_URL` in Switch's `.env` to its https address.

3. Start Switch with the override, from the Switch checkout. It mounts the adapter into Switch's published image, so nothing needs building. It was checked against image version 0.31.0.

   ```bash
   docker compose -f deploy/local/standalone-docker-compose.yml -f ../foundry/integrations/whatsapp/compose.whatsapp.yml --profile collab --profile gateway --project-directory . up -d
   ```

4. Create the Meta app and collect its five values. `docs/messaging-platforms/whatsapp.md` in the patched Switch checkout walks through it. Put them in Foundry's `.env` as the `WHATSAPP_` values, then run this from Foundry:

   ```bash
   uv run --env-file .env python tools/connect_whatsapp.py
   ```

   It prints the callback address to paste into Meta's webhook settings.

5. Write to the number from WhatsApp. Switch opens a room named after the person and their number, such as `SiteEngineerA_15550001111`, and replies that no agent is in it yet. The desk does not see that first message. Link the room to a client, then restart the desk:

   ```bash
   uv run --env-file .env python tools/link_chat.py "SiteEngineerA_15550001111" green-valley
   ```

To name a WhatsApp person as approver, use their Switch sender id in `FOUNDRY_APPROVER`: `@switch-whatsapp-<bridge id>-<lowercase name>_<number>:localhost`.

## Limits

- Meta only allows free-form messages within 24 hours of the person's last message. Outside that window WhatsApp refuses the send, including a card.
- WhatsApp can't remove buttons from a sent message. Pressing a used button does nothing.
- WhatsApp connections here are one to one, with no group chats, and one Meta app can be connected once.
- These stay plain text because the answer is free text or there is more than one question: asking what someone needs, asking what should change, and several questions at once.
- If the desk is not connected when a card opens, Switch shows "Host offline" with no buttons.

## What has been run

| What | State |
|---|---|
| The pull request's 122 tests on our Switch version, with our cards | 157 pass together with the card and tool surface tests |
| A real Switch with the adapter and Foundry's desk on a real model, against a local stand-in for Meta's API and made-up credentials: first message, linking, question buttons, list, typed answer, sign-off, ask for changes, delivery, pressing a used button | Run |
| Webhook signature check and Meta's verify-token check through real Switch | Run, against the same stand-in |
| `compose.whatsapp.yml` loading the adapter into the published image, and `git am` on a clean checkout | Run |
| Meta's real API, a real phone, a real tunnel | Not run. Needs a Meta app |
| Voice notes and files arriving from WhatsApp | Not run. Sending a sticker image was run against the stand-in only |
