# ═══════════════════════════════════════════════════════════════════════════════
#  crew_commands.py  ·  /crew set and /crew show
#  Add to bot.py:
#      from crew_commands import crew_group
#      bot.tree.add_command(crew_group)
#
#  Add to db.py migrations list:
#      "ALTER TABLE crews ADD COLUMN description    TEXT",
#      "ALTER TABLE crews ADD COLUMN jolly_roger_url TEXT",
#      "ALTER TABLE crews ADD COLUMN ship_name       TEXT",
#      "ALTER TABLE crews ADD COLUMN ship_url        TEXT",
#      "ALTER TABLE crews ADD COLUMN motto           TEXT",
#
#  Add to db.py (paste alongside other crew functions):
#      def set_crew_details(crew_id, description=None, jolly_roger_url=None,
#                           ship_name=None, ship_url=None, motto=None):
#          fields = []; values = []
#          for col, val in [("description", description),
#                           ("jolly_roger_url", jolly_roger_url),
#                           ("ship_name", ship_name),
#                           ("ship_url", ship_url),
#                           ("motto", motto)]:
#              if val is not None:
#                  fields.append(f"{col}=?"); values.append(val)
#          if not fields: return
#          values.append(crew_id)
#          db.execute(f"UPDATE crews SET {', '.join(fields)} WHERE id=?", values)
#          db.commit()
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import GUILD_ID


# ── Modal ─────────────────────────────────────────────────────────────────────

class CrewDetailsModal(discord.ui.Modal, title="Crew Details"):

    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Tell us about your crew...",
        max_length=300,
        required=False,
    )

    jolly_roger = discord.ui.TextInput(
        label="Jolly Roger URL",
        placeholder="https://  (image link for your crew's flag)",
        max_length=200,
        required=False,
    )

    ship_name = discord.ui.TextInput(
        label="Ship Name",
        placeholder="e.g. Thousand Sunny, Moby Dick...",
        max_length=64,
        required=False,
    )

    ship_url = discord.ui.TextInput(
        label="Ship Image URL",
        placeholder="https://  (image link for your ship)",
        max_length=200,
        required=False,
    )

    motto = discord.ui.TextInput(
        label="Motto",
        placeholder="Your crew's motto or any other detail...",
        max_length=100,
        required=False,
    )

    def __init__(self, crew_row):
        super().__init__()
        self.crew_id = crew_row["id"]
        if crew_row["description"]:
            self.description.default    = crew_row["description"]
        if crew_row["jolly_roger_url"]:
            self.jolly_roger.default    = crew_row["jolly_roger_url"]
        if crew_row["ship_name"]:
            self.ship_name.default      = crew_row["ship_name"]
        if crew_row["ship_url"]:
            self.ship_url.default       = crew_row["ship_url"]
        if crew_row["motto"]:
            self.motto.default          = crew_row["motto"]

    async def on_submit(self, interaction: discord.Interaction):
        db.set_crew_details(
            self.crew_id,
            description     = str(self.description).strip()  or None,
            jolly_roger_url = str(self.jolly_roger).strip()   or None,
            ship_name       = str(self.ship_name).strip()     or None,
            ship_url        = str(self.ship_url).strip()       or None,
            motto           = str(self.motto).strip()          or None,
        )
        await interaction.response.send_message(
            "Crew details updated!", ephemeral=True
        )


# ── Display helper ────────────────────────────────────────────────────────────

def _crew_embed(crew_row, guild: discord.Guild) -> discord.Embed:
    name    = crew_row["name"]
    captain = guild.get_member(int(crew_row["captain_id"])) if crew_row["captain_id"] else None
    bounty  = crew_row["bounty"] or 0
    members = db.get_crew_members(crew_row["id"])

    embed = discord.Embed(
        title=name,
        description=crew_row["description"] or "*No description set.*",
        color=int(crew_row["id"]) & 0xFFFFFF if crew_row["id"].isdigit() else 0x1a3f6b,
    )

    if crew_row["jolly_roger_url"]:
        embed.set_thumbnail(url=crew_row["jolly_roger_url"])

    if captain:
        embed.add_field(name="Captain",  value=captain.display_name, inline=True)

    embed.add_field(name="Members", value=str(len(members)),     inline=True)
    embed.add_field(name="Bounty",  value=f"฿{bounty:,}",        inline=True)

    if crew_row["ship_name"]:
        embed.add_field(name="Ship", value=crew_row["ship_name"], inline=True)

    if crew_row["motto"]:
        embed.add_field(name="Motto", value=f'*"{crew_row["motto"]}"*', inline=False)

    if crew_row["ship_url"]:
        embed.set_image(url=crew_row["ship_url"])

    return embed


# ── Crew command group ────────────────────────────────────────────────────────

crew_group = discord.app_commands.Group(
    name="crew",
    description="Crew information and management",
    guild_ids=[GUILD_ID],
)


@crew_group.command(name="set", description="Set your crew's details (captain only)")
async def crew_set(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)

    if not player or not player["crew_id"]:
        await interaction.response.send_message(
            "You're not in a crew.", ephemeral=True
        )
        return

    crew = db.get_crew(player["crew_id"])
    if not crew or crew["captain_id"] != uid:
        await interaction.response.send_message(
            "Only the captain can edit crew details.", ephemeral=True
        )
        return

    await interaction.response.send_modal(CrewDetailsModal(crew))


@crew_group.command(name="show", description="View a crew's details")
@discord.app_commands.describe(name="Crew name (leave empty for your own crew)")
async def crew_show(interaction: discord.Interaction, name: str = None):
    if name:
        crew = db.get_crew_by_name(name)
        if not crew:
            await interaction.response.send_message(
                f"No crew named **{name}** found.", ephemeral=True
            )
            return
    else:
        uid    = str(interaction.user.id)
        player = db.get_player(uid)
        if not player or not player["crew_id"]:
            await interaction.response.send_message(
                "You're not in a crew. Pass a crew name to look one up.", ephemeral=True
            )
            return
        crew = db.get_crew(player["crew_id"])
        if not crew:
            await interaction.response.send_message(
                "Couldn't find your crew.", ephemeral=True
            )
            return

    embed = _crew_embed(crew, interaction.guild)
    await interaction.response.send_message(embed=embed)
