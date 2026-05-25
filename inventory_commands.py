# ═══════════════════════════════════════════════════════════════════════════════
#  inventory_commands.py  ·  /inventory and /eat
#  Add to bot.py:
#      from inventory_commands import inventory_cmd, eat_cmd
#      bot.tree.add_command(inventory_cmd)
#      bot.tree.add_command(eat_cmd)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import MY_GUILD
from fruits import get_fruit_by_id, FRUITS

CAT_MAP = {
    "1": "Paramecia", "2": "Zoan",         "3": "Logia",
    "4": "Mythical Zoan", "5": "Ancient Zoan", "6": "Special Paramecia",
}


def _fruit_line(fruit_id):
    """Returns a display string for a fruit given its ID."""
    if not fruit_id:
        return None
    row = get_fruit_by_id(fruit_id)
    if not row:
        return fruit_id
    jap = (row.get("jap") or "").strip()
    eng = (row.get("eng") or "").strip()
    cat = CAT_MAP.get(row.get("cat", ""), "Unknown")
    return f"{jap}  ·  *{eng}*  ·  {cat}"


def _inventory_embed(member, player):
    embed = discord.Embed(title="Your inventory", color=0x1a3f6b)

    # berry — icon inline with bold value, no field title
    berry = player["berry"] or 0
    embed.add_field(name="🪙", value=f"**฿{berry:,}**", inline=True)

    # eaten fruit — only shown if they have one
    eaten_line = _fruit_line(player["fruit_id"])
    if eaten_line:
        embed.add_field(name="🍎", value=eaten_line, inline=True)

    # items — shown with backpack icon in the field title
    items = db.get_inventory(str(member.id))
    if items:
        lines = []
        for item in items:
            kws  = ", ".join(item.get("keywords", [])) or "no tags"
            lines.append(f"**{item['name']}** · {kws} · ×{item['qty']}")
        embed.add_field(name="🎒  Items", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🎒  Items", value="*Empty.*", inline=False)

    return embed


# ── /inventory ────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="inventory",
    description="View your inventory",
)
@discord.app_commands.guilds(MY_GUILD)
async def inventory_cmd(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message(
            "Register first with `/register`.", ephemeral=True
        )
        return
    embed = _inventory_embed(interaction.user, player)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /eat ──────────────────────────────────────────────────────────────────────

class EatConfirmView(discord.ui.View):
    def __init__(self, uid: str, fruit_id: str, fruit_name: str):
        super().__init__(timeout=60)
        self.uid        = uid
        self.fruit_id   = fruit_id
        self.fruit_name = fruit_name

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Eat it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your fruit.", ephemeral=True)
            return
        self.stop()
        for child in self.children:
            child.disabled = True

        success, result = db.eat_fruit(self.uid)
        if not success:
            msg = ("You don't have a held fruit." if result == "no_held_fruit"
                   else "You've already eaten a Devil Fruit.")
            await interaction.response.edit_message(content=msg, embed=None, view=self)
            return

        row  = get_fruit_by_id(result)
        name = (row.get("jap") or result) if row else result
        t1   = row.get("type1") or "Normal"
        t2   = row.get("type2") or "none"
        db.set_fighter_stats(self.uid)   # no stat changes, just ensures row exists
        # fruit_id is now set by eat_fruit — update fighter types
        db.set_player_fruit(self.uid, result)

        await interaction.response.edit_message(
            content=(
                f"You ate the **{name}**! "
                f"Your type is now `{t1}` / defence modifier `{t2}`.\n"
                f"*There is no going back.*"
            ),
            embed=None, view=self,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your fruit.", ephemeral=True)
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Cancelled. Your fruit is safe.", embed=None, view=self
        )


@discord.app_commands.command(
    name="eat",
    description="Eat your held Devil Fruit",
)
@discord.app_commands.guilds(MY_GUILD)
async def eat_cmd(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)

    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if not player["held_fruit_id"]:
        await interaction.response.send_message(
            "You don't have a fruit to eat. A GM can give you one.", ephemeral=True
        )
        return

    if player["fruit_id"]:
        await interaction.response.send_message(
            "You've already eaten a Devil Fruit. Only one per person.",
            ephemeral=True,
        )
        return

    row  = get_fruit_by_id(player["held_fruit_id"])
    name = (row.get("jap") or player["held_fruit_id"]) if row else player["held_fruit_id"]

    embed = discord.Embed(
        title=f"Eat the {name}?",
        description=(
            f"Eating a Devil Fruit is **permanent and irreversible**.\n"
            f"You will lose the ability to swim and gain its power."
        ),
        color=0xe05555,
    )
    view = EatConfirmView(uid=uid, fruit_id=player["held_fruit_id"], fruit_name=name)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
