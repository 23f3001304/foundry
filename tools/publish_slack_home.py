"""Publishes Foundry's page on the Slack app's Home tab for everyone in the workspace. Slack keeps one page per person, so run it again after someone joins.

uv run --env-file .env python tools/publish_slack_home.py foundry-approvals
"""

import os
import sys

import httpx

API = "https://slack.com/api"


def home_view(channel: str, picture: str) -> dict:
    def section(words: str) -> dict:
        return {"type": "section", "text": {"type": "mrkdwn", "text": words}}

    opening = section("*Foundry*\nYour onboard assistant, for work that needs a lot of people to get done.")
    opening["accessory"] = {"type": "image", "image_url": picture, "alt_text": "Foundry"}
    return {
        "type": "home",
        "blocks": [
            opening,
            {"type": "divider"},
            section("*How it works*\nAsk for something in chat. Foundry works out who owes what and asks them, and asks again when someone goes quiet. Then the work gets made and reviewed, and one card comes to you."),
            section("*Your part*\nApprove the card, or ask for changes. Nothing is delivered until you approve it."),
            section(f"*Where the cards arrive*\nIn this workspace they come to #{channel}. The first time you press one, Slack may ask you to link your account."),
            section("*Who said that?*\nEvery decision goes to the log, so the whole chain behind a piece of work is there on the dashboard."),
        ],
    }


def people(slack: httpx.Client) -> list[str]:
    found, cursor = [], ""
    while True:
        page = slack.get("/users.list", params={"limit": 200, "cursor": cursor}).json()
        if not page.get("ok"):
            raise SystemExit(f"Slack wouldn't list the workspace's people: {page.get('error')}")
        found += [member["id"] for member in page["members"] if not member.get("is_bot") and not member.get("deleted") and member["id"] != "USLACKBOT"]
        cursor = page.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return found


def publish(slack: httpx.Client, channel: str) -> tuple[int, int]:
    me = slack.post("/auth.test").json()
    picture = slack.get("/users.info", params={"user": me["user_id"]}).json()["user"]["profile"]["image_512"]
    view = home_view(channel, picture)
    published = failed = 0
    for person in people(slack):
        answer = slack.post("/views.publish", json={"user_id": person, "view": view}).json()
        if answer.get("ok"):
            published += 1
        else:
            failed += 1
            print(f"Slack refused one person's page: {answer.get('error')}")
    return published, failed


def main(arguments: list[str]) -> None:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise SystemExit("Put SLACK_BOT_TOKEN in .env first.")
    channel = arguments[0] if arguments else "foundry-approvals"
    with httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30, trust_env=False) as slack:
        published, failed = publish(slack, channel)
    print(f"Home tab published: {published}, refused: {failed}.")


if __name__ == "__main__":
    main(sys.argv[1:])
