from typing import Dict
from uuid import UUID, uuid4
from html import escape as esc
import time

from maubot import MessageEvent

from .base import Command, with_client
from ..api import LinearClient
from ..api.types import Label


LabelChanges = Dict[UUID, Dict[str, Label]]


def _format_change_message(create: LabelChanges, update: LabelChanges,
                           hacky_team_names: Dict[UUID, str]) -> str:
    messages = []
    for team_id, team_name in hacky_team_names.items():
        team_messages = [f"<h3>{team_name}</h3>"]

        if len(create[team_id]) > 0:
            team_messages.append("<h5>Labels to create</h5>")
            team_messages.append("<ul>")
            for label in create[team_id].values():
                label_msg = f"<font color='{label.color}'>⬤</font> {esc(label.name)}"
                if label.description:
                    label_msg = f"{label_msg}: {esc(label.description)}"
                label_msg = f"{label_msg} (based on {label.team.name})"
                team_messages.append(f"<li>{label_msg}</li>")
            team_messages.append("</ul>")

        if len(update[team_id]) > 0:
            team_messages.append("<h5>Labels to update</h5>")
            team_messages.append("<ul>")
            for label in update[team_id].values():
                label_msg = f"<font color='{label.color}'>⬤</font> {esc(label.name)}"
                if label.description:
                    label_msg = f"{label_msg}: {esc(label.description)}"
                label_msg = f"{label_msg} (changed in {label.team.name})"
                team_messages.append(f"<li>{label_msg}</li>")
            team_messages.append("</ul>")

        if len(team_messages) > 1:
            messages.append("\n".join(team_messages))
    return "\n".join(messages)


class CommandSyncLabels(Command):
    @Command.linear.subcommand(help="Sync Linear labels between teams")
    @with_client()
    async def sync_labels(self, evt: MessageEvent, client: LinearClient) -> None:
        reaction_id = await evt.react("👀")
        teams = await client.get_all_labels()
        create_labels: LabelChanges = {team_id: {} for team_id in teams.keys()}
        update_labels: LabelChanges = {team_id: {} for team_id in teams.keys()}
        hacky_team_names = {}
        for team_labels in teams.values():
            for label in team_labels.values():
                hacky_team_names[label.team.id] = label.team.name
                for other_team_id, other_team_labels in teams.items():
                    if label.name not in other_team_labels:
                        existing_create = create_labels[other_team_id].get(label.name)
                        if (existing_create is None
                                or existing_create.updated_at < label.updated_at):
                            create_labels[other_team_id][label.name] = label
                    else:
                        existing_label = other_team_labels[label.name]
                        existing_update = update_labels[other_team_id].get(label.name)
                        if (not existing_label.meta_equals(label)
                                and existing_label.updated_at < label.updated_at
                                and (existing_update is None
                                     or existing_update.updated_at < label.updated_at)):
                            update_labels[other_team_id][label.name] = label

        count = sum(len(labels) for labels in create_labels.values())
        count += sum(len(labels) for labels in update_labels.values())
        done = 0
        last_update = time.time()
        update_interval = 5

        if count == 0:
            await evt.reply("All teams are up to date")
            return

        await evt.client.redact(evt.room_id, reaction_id)
        await evt.reply(_format_change_message(create_labels, update_labels, hacky_team_names),
                        allow_html=True, markdown=False)
        progress_event_id = await evt.reply(f"Progress: {done}/{count}")

        async def _update_progress() -> None:
            nonlocal last_update, done
            done += 1
            if last_update + update_interval < time.time():
                last_update = time.time()
                await evt.respond(f"Progress: {done}/{count}", edits=progress_event_id)

        for team_id, labels in create_labels.items():
            for label in labels.values():
                self.bot.log.debug(f"Creating {label.name} in {hacky_team_names[team_id]} "
                                   f"based on {label.team.name}")
                new_label_id = uuid4()
                self.bot.linear_webhook.ignore_uuids.add(new_label_id)
                await client.create_label(team_id, name=label.name, description=label.description,
                                          color=label.color, label_id=new_label_id)
                self.bot.labels.put(team_id, label.name, new_label_id)
                await _update_progress()
        for team_id, labels in update_labels.items():
            for label in labels.values():
                old_label = teams[team_id][label.name]
                self.bot.log.debug(f"Updating {label.name} in {old_label.team.name} "
                                   f"based on {label.team.name}")
                self.bot.linear_webhook.ignore_uuids.add(old_label.id)
                await client.update_label(old_label.id, name=label.name,
                                          description=label.description, color=label.color)
                await _update_progress()

        await evt.respond("All done!", edits=progress_event_id)
