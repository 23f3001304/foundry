"""Takes approved work out to the outside room. Nothing else may post files there as final."""

from pathlib import Path

from foundry.jobs import Job, State, advance
from foundry.switch_client import SwitchClient

DELIVERED = "Here is your final work."


class NotApproved(Exception):
    pass


def deliver(job: Job, client: SwitchClient, outside_room_id: str) -> None:
    if job.state is not State.APPROVED:
        raise NotApproved(f"Job {job.id} is {job.state.value}, not approved.")
    client.post_message(outside_room_id, DELIVERED)
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
