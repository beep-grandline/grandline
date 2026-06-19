# ═══════════════════════════════════════════════════════════════════════════════
#  cook_commands.py  ·  /cook cookbook (add/list/modify/delete) + /cook serve
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


def _apply_meal_effect(uid: str, meal_type: str) -> str:
    """Apply a meal's effect to a player and return a short note string."""
    if meal_type == "stamina":
        db.add_walk_rolls(uid, game.STAMINA_MEAL_ROLLS, game.WALK_ROLL_OVERFILL)
        return f"💨 Stamina restored — up to {game.WALK_ROLL_OVERFILL} walk moves banked."
    if meal_type == "hearty":
        db.set_hearty_buff(uid, 1)
        return "💪 +10% to all stats in the next battle."
    if meal_type == "recovery":
        db.set_recovery_until(uid, time.time() + game.RECOVERY_MEAL_HOURS * 3600)
        return f"❤️ Recovery boosted for the next {game.RECOVERY_MEAL_HOURS} hours."
    return "...it tasted like nothing."


# ── Groups ────────────────────────────────────────────────────────────────────

cook_group = discord.app_commands.Group(
    name="cook",
    description="Cook meals for your crew",
    guild_ids=[GUILD_ID],
)

cookbook_group = discord.app_commands.Group(
    name="cookbook",
    description="Manage your recipes",
)
cook_group.add_command(cookbook_group)


# ── Shared autocomplete ───────────────────────────────────────────────────────

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


# ── /cook cookbook add ────────────────────────────────────────────────────────

@cookbook_group.command(name="add", description="Add a new signature dish to your cookbook")
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
async def cookbook_add(
    interaction: discord.Interaction,
    name: str,
    type: str,
    description: str,
    extra: str = None,
    url: str = None,
):
    try:
        uid = str(interaction.user.id)
        if not db.get_player(uid):
            await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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
    except discord.NotFound:
        pass


# ── /cook cookbook list ───────────────────────────────────────────────────────

@cookbook_group.command(name="list", description="View all your recipes")
async def cookbook_list(interaction: discord.Interaction):
    try:
        uid     = str(interaction.user.id)
        recipes = db.get_recipes(uid)
        if not recipes:
            await interaction.response.send_message(
                "Your cookbook is empty. Add a dish with `/cook cookbook add`.", ephemeral=True
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
    except discord.NotFound:
        pass


# ── /cook cookbook modify ─────────────────────────────────────────────────────

class ModifyModal(discord.ui.Modal):
    def __init__(self, uid: str, recipe: dict):
        super().__init__(title=f"Edit: {recipe['name'][:40]}")
        self.uid    = uid
        self.recipe = recipe

        self.field_desc = discord.ui.TextInput(
            label="Description",
            default=recipe.get("description", ""),
            max_length=300,
            required=False,
        )
        self.field_url = discord.ui.TextInput(
            label="Image URL",
            default=recipe.get("url", ""),
            max_length=500,
            required=False,
        )
        self.add_item(self.field_desc)
        self.add_item(self.field_url)

    async def on_submit(self, interaction: discord.Interaction):
        db.update_recipe(self.uid, self.recipe["name"], {
            "description": str(self.field_desc.value)[:300],
            "url":         str(self.field_url.value).strip(),
        })
        await interaction.response.send_message(
            f"✏️ **{self.recipe['name']}** updated.", ephemeral=True
        )


@cookbook_group.command(name="modify", description="Edit an existing recipe's description or image")
@discord.app_commands.describe(dish="Recipe to edit")
@discord.app_commands.autocomplete(dish=_recipe_autocomplete)
async def cookbook_modify(interaction: discord.Interaction, dish: str):
    try:
        uid    = str(interaction.user.id)
        recipe = next((r for r in db.get_recipes(uid) if r["name"].lower() == dish.lower()), None)
        if not recipe:
            await interaction.response.send_message(
                "Recipe not found in your cookbook.", ephemeral=True
            )
            return
        await interaction.response.send_modal(ModifyModal(uid=uid, recipe=recipe))
    except discord.NotFound:
        pass


# ── /cook cookbook delete ─────────────────────────────────────────────────────

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, uid: str, name: str):
        super().__init__(timeout=60)
        self.uid  = uid
        self.name = name

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your cookbook.", ephemeral=True)
            return
        db.delete_recipe(self.uid, self.name)
        self.stop()
        await interaction.response.edit_message(
            content=f"🗑️ **{self.name}** deleted.", view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


@cookbook_group.command(name="delete", description="Remove a recipe from your cookbook")
@discord.app_commands.describe(dish="Recipe to delete")
@discord.app_commands.autocomplete(dish=_recipe_autocomplete)
async def cookbook_delete(interaction: discord.Interaction, dish: str):
    try:
        uid    = str(interaction.user.id)
        recipe = next((r for r in db.get_recipes(uid) if r["name"].lower() == dish.lower()), None)
        if not recipe:
            await interaction.response.send_message(
                "Recipe not found in your cookbook.", ephemeral=True
            )
            return
        view = ConfirmDeleteView(uid=uid, name=recipe["name"])
        await interaction.response.send_message(
            f"Delete **{recipe['name']}**? This can't be undone.", view=view, ephemeral=True
        )
    except discord.NotFound:
        pass


# ── /cook serve ───────────────────────────────────────────────────────────────

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
            await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
            return
        if not player["crew_id"] or player["crew_id"] != self.crew_id:
            await interaction.response.send_message(
                "This meal is for the cook's crew only.", ephemeral=True
            )
            return
        if uid in self.eaten:
            await interaction.response.send_message("You've already had your share!", ephemeral=True)
            return

        note = _apply_meal_effect(uid, self.recipe["type"])
        self.eaten.add(uid)
        await interaction.response.send_message(
            f"You eat **{self.recipe['name']}**. {note}", ephemeral=True
        )


@cook_group.command(name="serve", description="Serve one of your dishes to the crew")
@discord.app_commands.describe(dish="A recipe from your cookbook")
@discord.app_commands.autocomplete(dish=_recipe_autocomplete)
async def cook_serve(interaction: discord.Interaction, dish: str):
    try:
        uid    = str(interaction.user.id)
        player = db.get_player(uid)
        if not player:
            await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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
                "That dish isn't in your cookbook. Use `/cook cookbook add` to create it.", ephemeral=True
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
    except discord.NotFound:
        pass


# ── /cook feed ────────────────────────────────────────────────────────────────

class FeedView(discord.ui.View):
    def __init__(self, cook_id: str, target_id: str, recipe: dict, full_embed: discord.Embed):
        super().__init__(timeout=300)
        self.cook_id    = cook_id
        self.target_id  = target_id
        self.recipe     = recipe
        self.full_embed = full_embed

    @discord.ui.button(label="Eat 🍽️", style=discord.ButtonStyle.success)
    async def eat(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.target_id:
            await interaction.response.send_message("That's not for you.", ephemeral=True)
            return

        note = _apply_meal_effect(self.target_id, self.recipe["type"])

        # full recipe embed + effect note, ephemeral to the eater
        result_embed = discord.Embed.from_dict(self.full_embed.to_dict())
        result_embed.add_field(name="Effect", value=note, inline=False)
        await interaction.response.send_message(embed=result_embed, ephemeral=True)

        # disable the button on the public message
        button.disabled = True
        button.label = "Eaten"
        await interaction.message.edit(view=self)
        self.stop()


@cook_group.command(name="feed", description="Serve a dish directly to one person")
@discord.app_commands.describe(dish="A recipe from your cookbook", target="Who to feed")
@discord.app_commands.autocomplete(dish=_recipe_autocomplete)
async def cook_feed(interaction: discord.Interaction, dish: str, target: discord.Member):
    try:
        uid = str(interaction.user.id)
        player = db.get_player(uid)
        if not player:
            await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
            return
        if not _is_cook(interaction.user):
            await interaction.response.send_message("Only a **Cook** can serve meals.", ephemeral=True)
            return

        tid = str(target.id)
        if not db.get_player(tid):
            await interaction.response.send_message(
                f"{target.display_name} isn't registered yet.", ephemeral=True
            )
            return

        recipe = next(
            (r for r in db.get_recipes(uid) if r["name"].lower() == dish.lower()), None
        )
        if not recipe:
            await interaction.response.send_message(
                "That dish isn't in your cookbook. Use `/cook cookbook add` to create it.", ephemeral=True
            )
            return

        kw = " · ".join(k.upper() for k in recipe.get("keywords", []))

        # full embed stored in the view for sending ephemerally on eat
        full_embed = discord.Embed(
            title=f"🍽️ {recipe['name']}  ·  `{kw}`",
            description=(
                f"{recipe.get('description', '')}\n\n"
                f"*{MEAL_TYPE_BLURB.get(recipe['type'], '')}*"
            ),
            color=0xd98e32,
        )
        if recipe.get("url"):
            full_embed.set_image(url=recipe["url"])
        full_embed.set_footer(text=f"Prepared by {interaction.user.display_name}")

        view = FeedView(cook_id=uid, target_id=tid, recipe=recipe, full_embed=full_embed)
        blurb = MEAL_TYPE_BLURB.get(recipe["type"], "a meal")
        await interaction.response.send_message(
            f"{interaction.user.display_name} wants to feed {target.mention} **{recipe['name']}** ({blurb})",
            view=view,
        )
    except discord.NotFound:
        pass

