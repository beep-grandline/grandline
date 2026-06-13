# ═══════════════════════════════════════════════════════════════════════════════
#  cook_commands.py  ·  /cook recipe, cookbook, serve — crew meals with buffs
#  Add to bot.py:
#      from cook_commands import cook_group
#      bot.tree.add_command(cook_group)
# ═══════════════════════════════════════════════════════════════════════════════

import time

import discord
import db
import game
from config import GUILD_ID

MEAL_TYPES     = ["stamina", "hearty", "recovery"]
EXTRA_KEYWORDS = ["poison", "spicy"]   # no mechanical effect yet

MEAL_TYPE_BLURB = {
    "stamina":  "restores stamina for travel on foot",
    "hearty":   "+10% to all stats for the next battle",
    "recovery": "speeds up natural recovery for a few hours",
}

SERVE_WINDOW_SECONDS = 3600  # crew has 1 hour to eat


def _is_cook(member: discord.Member) -> bool:
    return any(role.name.lower() == "cook" for role in getattr(member, "roles", []))


cook_group = discord.app_commands.Group(
    name="cook",
    description="Cook meals for your crew",
    guild_ids=[GUILD_ID],
)


# ── /cook recipe ──────────────────────────────────────────────────────────────

@cook_group.command(name="recipe", description="Create a new signature dish")
@discord.app_commands.describe(
    name="Name of your dish",
    type="What the meal does",
    description="Flavor text shown when you serve it",
    extra="Optional extra keyword",
    url="Optional image URL for the dish",
)
@discord.app_commands.choices(
    type=[discord.app_commands.Choice(name=t.title(), value=t) for t in MEAL_TYPES],
    extra=[discord.app_commands.Choice(name=k.title(), value=k) for k in EXTRA_KEYWORDS],
)
async def cook_recipe(
    interaction: discord.Interaction,
    name: str,
    type: str,
    description: str,
    extra: str = None,
    url: str = None,
):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return
    if not _is_cook(interaction.user):
        await interaction.response.send_message("Only a **Cook** can create recipes.", ephemeral=True)
        return

    recipes = db.get_recipes(uid)
    if any(r["name"].lower() == name.lower() for r in recipes):
        await interaction.response.send_message(
            f"You already have a recipe called **{name}**.", ephemeral=True
        )
        return
    if len(recipes) >= 25:
        await interaction.response.send_message("Your cookbook is full (25 recipes).", ephemeral=True)
        return

    keywords = [type] + ([extra] if extra else [])
    db.add_recipe(uid, {
        "name":        name[:80],
        "type":        type,
        "keywords":    keywords,
        "description": description[:300],
        "url":         (url or "").strip(),
    })
    await interaction.response.send_message(
        f"📖 **{name}** added to your cookbook — *{', '.join(k.upper() for k in keywords)}*.",
        ephemeral=True,
    )


# ── /cook cookbook ────────────────────────────────────────────────────────────

@cook_group.command(name="cookbook", description="View your recipes")
async def cook_cookbook(interaction: discord.Interaction):
    uid     = str(interaction.user.id)
    recipes = db.get_recipes(uid)
    if not recipes:
        await interaction.response.send_message(
            "Your cookbook is empty. Create a dish with `/cook recipe`.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"📖 {interaction.user.display_name}'s Cookbook",
        color=0xd98e32,
    )
    for r in recipes[:25]:
        kw = ", ".join(k.upper() for k in r.get("keywords", []))
        embed.add_field(
            name=f"{r['name']}  ·  {kw}",
            value=r.get("description") or "​",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /cook serve ───────────────────────────────────────────────────────────────

async def _recipe_autocomplete(interaction: discord.Interaction, current: str):
    try:
        recipes = db.get_recipes(str(interaction.user.id))
        return [
            discord.app_commands.Choice(name=r["name"][:100], value=r["name"][:100])
            for r in recipes
            if current.lower() in r["name"].lower()
        ][:25]
    except Exception:
        return []


class ServeView(discord.ui.View):
    def __init__(self, cook_id: str, crew_id: str, recipe: dict):
        super().__init__(timeout=SERVE_WINDOW_SECONDS)
        self.cook_id = cook_id
        self.crew_id = crew_id
        self.recipe  = recipe
        self.eaten   = set()
        self.message = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="Eat", emoji="🍴", style=discord.ButtonStyle.success)
    async def eat(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid    = str(interaction.user.id)
        player = db.get_player(uid)
        if not player:
            await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
            return
        if not player["crew_id"] or player["crew_id"] != self.crew_id:
            await interaction.response.send_message(
                "This meal is for the cook's crew only.", ephemeral=True
            )
            return
        if uid in self.eaten:
            await interaction.response.send_message("You've already had your share!", ephemeral=True)
            return

        meal_type = self.recipe["type"]
        if meal_type == "stamina":
            db.add_walk_rolls(uid, game.STAMINA_MEAL_ROLLS, game.WALK_ROLL_OVERFILL)
            note = f"💨 Stamina restored — up to {game.WALK_ROLL_OVERFILL} walk moves banked."
        elif meal_type == "hearty":
            db.set_hearty_buff(uid, 1)
            note = "💪 You feel stronger — +10% to all stats in your next battle."
        elif meal_type == "recovery":
            db.set_recovery_until(uid, time.time() + game.RECOVERY_MEAL_HOURS * 3600)
            note = f"❤️ Recovery boosted for the next {game.RECOVERY_MEAL_HOURS} hours."
        else:
            note = "...it tasted like nothing."

        self.eaten.add(uid)
        await interaction.response.send_message(
            f"You eat **{self.recipe['name']}**. {note}", ephemeral=True
        )


@cook_group.command(name="serve", description="Serve one of your dishes to the crew")
@discord.app_commands.describe(dish="A recipe from your cookbook")
@discord.app_commands.autocomplete(dish=_recipe_autocomplete)
async def cook_serve(interaction: discord.Interaction, dish: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return
    if not _is_cook(interaction.user):
        await interaction.response.send_message("Only a **Cook** can serve meals.", ephemeral=True)
        return
    if not player["crew_id"]:
        await interaction.response.send_message("You need to be in a crew to serve a meal.", ephemeral=True)
        return

    recipe = next(
        (r for r in db.get_recipes(uid) if r["name"].lower() == dish.lower()), None
    )
    if not recipe:
        await interaction.response.send_message(
            "That dish isn't in your cookbook. Use `/cook recipe` to create it.", ephemeral=True
        )
        return

    kw    = " · ".join(k.upper() for k in recipe.get("keywords", []))
    embed = discord.Embed(
        title=f"🍽️ {recipe['name']}  ·  `{kw}`",
        description=(
            f"{recipe.get('description', '')}\n\n"
            f"*{MEAL_TYPE_BLURB.get(recipe['type'], '')}*"
        ),
        color=0xd98e32,
    )
    if recipe.get("url"):
        embed.set_image(url=recipe["url"])
    embed.set_footer(text=f"Prepared by {interaction.user.display_name}")

    view = ServeView(cook_id=uid, crew_id=player["crew_id"], recipe=recipe)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()
