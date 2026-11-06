"""Takes approved work out to the outside room. Nothing else may post files there as final."""

import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from foundry.cards import ROOM_GONE
from foundry.coordinator import ABOUT_THE_REQUEST
from foundry.jobs import Job, State, advance
from foundry.switch_client import SwitchClient

logger = logging.getLogger(__name__)

DELIVERED = "Here is your final work."
# What the answers of a job that makes nothing are called in Job.answers_sent. A file goes by its path.
THE_WORDS = "words"
FILE_NOT_ATTACHED = "{name} could not be attached, so the answers name it and it is not with them."


class NotApproved(Exception):
    pass


def will_never_pass(error: httpx.HTTPError) -> bool:
    # The room is gone, or Switch says this message itself is wrong, and another try gets the same answer.
    return isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (*ROOM_GONE, *ABOUT_THE_REQUEST)


def post_answer_file(job: Job, client: SwitchClient, room_id: str, path: str, caption: str, part: str, save: Callable[[Job], None]) -> None:
    # A file that went is not sent again. One that never can go, or has gone from the disk, doesn't hold up the words, which name it. One Switch refuses for now raises, and is tried again.
    if part in job.answers_sent:
        return
    try:
        client.post_file(room_id, path, caption)
    except (OSError, httpx.HTTPError) as error:
        if isinstance(error, httpx.HTTPError) and not will_never_pass(error):
            raise
        logger.warning("Could not attach %s for job %s, so it is left out: %s", Path(path).name, job.id, error)
        job.attention.append(FILE_NOT_ATTACHED.format(name=Path(path).name))
    job.answers_sent.append(part)
    save(job)


def deliver_answers(job: Job, client: SwitchClient, outside_room_id: str, save: Callable[[Job], None]) -> None:
    # Each part is saved as sent, so a try after a failure or a restart carries on from the first that has not gone. What it went out as is on the job, so nothing can be lost.
    if job.state is not State.APPROVED:
        raise NotApproved(f"Job {job.id} is {job.state.value}, not approved.")
    if THE_WORDS not in job.answers_sent:
        client.post_message(outside_room_id, job.report)
        job.answers_sent.append(THE_WORDS)
        save(job)
    for path in job.artifacts:
        post_answer_file(job, client, outside_room_id, path, Path(path).name, path, save)


def deliver(job: Job, client: SwitchClient, outside_room_id: str, words: str = DELIVERED) -> None:
    if job.state is not State.APPROVED:
        raise NotApproved(f"Job {job.id} is {job.state.value}, not approved.")
    client.post_message(outside_room_id, words)
    for path in job.artifacts:
        client.post_file(outside_room_id, path, Path(path).name)
    advance(job, "delivered")


def deliver_report(job: Job, client: SwitchClient, room_ids: list[str], heading: str = "") -> None:
    if job.state is not State.APPROVED:
        raise NotApproved(f"Job {job.id} is {job.state.value}, not approved.")
    # A day's report names its day, so it still reads right when it is found later.
    text = f"{heading}\n{job.report}" if heading else job.report
    for room_id in room_ids:
        client.post_message(room_id, text)
    advance(job, "delivered")
