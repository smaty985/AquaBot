import discord
from discord import app_commands
from discord.ext import commands

import json
import os
import asyncio
import random
import aiohttp
import requests

from datetime import datetime, timedelta

from colorama import Fore, Style, init

init(autoreset=True)


# ============================================================
# KONFIGURÁCIÓ
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

# Roblox Open Cloud
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")
ROBLOX_GROUP_ID = 763709782

# Discord Role ID -> Roblox Group Role ID
ROBLOX_ROLE_BINDS = {
    1542527015738151034: 1,
    1542530743346135111: 2,
}

# Roblox role, amire visszaállítjuk a tagot,
# ha egy bindelt Discord role-t elvesz.
ROBLOX_DEFAULT_ROLE_ID = None

AUTOROLE_NAME = "Játékos"
STAFF_ROLE_NAME = "🎫 | Ticket Felelős"

DATA_FILE = "data.json"

# Minecraft szerver státusz
MINECRAFT_SERVER_IP = "play.aquazone.hu"
MINECRAFT_STATUS_URL = f"https://api.mcsrvstat.us/3/{MINECRAFT_SERVER_IP}"
STATUS_REFRESH_SECONDS = 600  # 10 perc

# /status által létrehozott üzenetekhez tartozó háttérfeladatok
status_tasks = {}
status_states = {}


# ============================================================
# DISCORD BEÁLLÍTÁSOK
# ============================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix="/",
    intents=intents,
    help_command=None
)


# ============================================================
# ADATKEZELÉS
# ============================================================

def load_data():
    default_data = {
        "warns": {},
        "guild_settings": {},
        "roblox_links": {},
        "points": {}
    }

    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                default_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        return default_data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    except (json.JSONDecodeError, OSError):
        data = default_data

    data.setdefault("warns", {})
    data.setdefault("guild_settings", {})
    data.setdefault("roblox_links", {})
    data.setdefault("points", {})

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def get_guild_settings(guild_id):
    data = load_data()

    return data.setdefault(
        "guild_settings",
        {}
    ).setdefault(
        str(guild_id),
        {}
    )


# ============================================================
# SEGÉDFÜGGVÉNYEK
# ============================================================

def member_avatar(member):
    if member.avatar:
        return member.avatar.url

    return member.default_avatar.url


async def send_log(
    guild,
    title,
    description,
    color=discord.Color.blue()
):
    if guild is None:
        return

    data = load_data()

    settings = data.get(
        "guild_settings",
        {}
    ).get(
        str(guild.id),
        {}
    )

    log_channel_id = settings.get("log_channel_id")

    if not log_channel_id:
        return

    channel = guild.get_channel(
        int(log_channel_id)
    )

    if channel is None:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )

    embed.set_footer(
        text="Particle • Moderation & Logging"
    )

    try:
        await channel.send(embed=embed)

    except Exception as e:
        print(
            f"{Fore.RED}[LOG ERROR]"
            f"{Style.RESET_ALL} {e}"
        )


# ============================================================
# ROBLOX OPEN CLOUD
# ============================================================

def roblox_configured():
    return bool(
        ROBLOX_API_KEY and ROBLOX_GROUP_ID
    )


async def get_roblox_membership(roblox_user_id):
    """
    Megkeresi a Roblox user group membershipét.
    """

    if not roblox_configured():
        return None, (
            "A Roblox Open Cloud nincs konfigurálva."
        )

    url = (
        f"https://apis.roblox.com/cloud/v2/groups/"
        f"{ROBLOX_GROUP_ID}/memberships"
    )

    headers = {
        "x-api-key": ROBLOX_API_KEY
    }

    async with aiohttp.ClientSession() as session:

        page_token = None

        while True:

            params = {
                "maxPageSize": 100
            }

            if page_token:
                params["pageToken"] = page_token

            try:
                async with session.get(
                    url,
                    headers=headers,
                    params=params
                ) as response:

                    if response.status != 200:
                        text = await response.text()

                        return None, (
                            f"Roblox API hiba "
                            f"{response.status}: {text}"
                        )

                    data = await response.json()

            except aiohttp.ClientError as e:
                return None, (
                    f"Roblox kapcsolat hiba: {e}"
                )

            memberships = data.get(
                "groupMemberships",
                []
            )

            for membership in memberships:

                user = membership.get(
                    "user",
                    {}
                )

                user_id = user.get("userId")

                if str(user_id) == str(roblox_user_id):

                    path = membership.get("path")

                    if path:
                        return path, None

            page_token = data.get(
                "nextPageToken"
            )

            if not page_token:
                break

    return None, (
        "A Roblox felhasználó nem tagja ennek a Groupnak."
    )


async def set_roblox_rank(
    roblox_user_id,
    roblox_role_id
):
    """
    Roblox Group role beállítása.
    """

    membership_path, error = (
        await get_roblox_membership(
            roblox_user_id
        )
    )

    if error:
        return False, error

    url = (
        f"https://apis.roblox.com/cloud/v2/"
        f"{membership_path}:assignRole"
    )

    headers = {
        "x-api-key": ROBLOX_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "role": (
            f"groups/{ROBLOX_GROUP_ID}/roles/"
            f"{roblox_role_id}"
        )
    }

    async with aiohttp.ClientSession() as session:

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload
            ) as response:

                if response.status in (
                    200,
                    202,
                    204
                ):
                    return True, (
                        "Roblox rank sikeresen módosítva."
                    )

                text = await response.text()

                return False, (
                    f"Roblox API hiba "
                    f"{response.status}: {text}"
                )

        except aiohttp.ClientError as e:
            return False, (
                f"Roblox kapcsolat hiba: {e}"
            )


async def sync_roblox_role(
    member,
    discord_role
):
    """
    Egy Discord role hozzáadásakor
    a hozzá tartozó Roblox rank beállítása.
    """

    roblox_role_id = ROBLOX_ROLE_BINDS.get(
        discord_role.id
    )

    if not roblox_role_id:
        return

    data = load_data()

    roblox_user_id = data.get(
        "roblox_links",
        {}
    ).get(
        str(member.id)
    )

    if not roblox_user_id:

        print(
            f"{Fore.YELLOW}"
            f"[ROBLOX]"
            f"{Style.RESET_ALL} "
            f"{member} nincs összekötve Roblox fiókkal."
        )

        return

    success, message = await set_roblox_rank(
        roblox_user_id,
        roblox_role_id
    )

    if success:

        print(
            f"{Fore.GREEN}"
            f"[ROBLOX]"
            f"{Style.RESET_ALL} "
            f"{member} -> "
            f"Discord: {discord_role.name} -> "
            f"Roblox Role ID: {roblox_role_id}"
        )

        await send_log(
            member.guild,
            "🎮 Roblox rank frissítve",
            (
                f"**Discord tag:** {member.mention}\n"
                f"**Discord role:** {discord_role.mention}\n"
                f"**Roblox User ID:** {roblox_user_id}\n"
                f"**Roblox Role ID:** {roblox_role_id}"
            ),
            discord.Color.green()
        )

    else:

        print(
            f"{Fore.RED}"
            f"[ROBLOX ERROR]"
            f"{Style.RESET_ALL} "
            f"{member}: {message}"
        )

        await send_log(
            member.guild,
            "❌ Roblox rank hiba",
            (
                f"**Tag:** {member.mention}\n"
                f"**Discord role:** {discord_role.mention}\n"
                f"**Hiba:** {message}"
            ),
            discord.Color.red()
        )


# ============================================================
# ROBLOX LINK
# ============================================================

@bot.tree.command(
    name="linkroblox",
    description="Discord fiók összekapcsolása Roblox fiókkal"
)
@app_commands.describe(
    roblox_user_id="A Roblox User ID-d"
)
async def linkroblox_slash(
    interaction: discord.Interaction,
    roblox_user_id: str
):

    if not roblox_user_id.isdigit():

        await interaction.response.send_message(
            "❌ A Roblox User ID csak szám lehet.",
            ephemeral=True
        )

        return

    if not roblox_configured():

        await interaction.response.send_message(
            "❌ A Roblox rendszer jelenleg nincs konfigurálva.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    membership_path, error = (
        await get_roblox_membership(
            roblox_user_id
        )
    )

    if error:

        await interaction.followup.send(
            (
                "❌ Nem sikerült ellenőrizni "
                "a Roblox fiókot.\n"
                f"**Hiba:** {error}"
            ),
            ephemeral=True
        )

        return

    if not membership_path:

        await interaction.followup.send(
            (
                "❌ Ez a Roblox felhasználó "
                "nem tagja a beállított Groupnak."
            ),
            ephemeral=True
        )

        return

    data = load_data()

    data.setdefault(
        "roblox_links",
        {}
    )

    data["roblox_links"][
        str(interaction.user.id)
    ] = int(roblox_user_id)

    save_data(data)

    await interaction.followup.send(
        (
            "✅ **Roblox fiók sikeresen összekapcsolva!**\n\n"
            f"**Roblox User ID:** {roblox_user_id}\n"
            f"**Discord:** {interaction.user.mention}"
        ),
        ephemeral=True
    )

    await send_log(
        interaction.guild,
        "🔗 Roblox fiók összekapcsolva",
        (
            f"**Discord:** {interaction.user.mention}\n"
            f"**Roblox User ID:** {roblox_user_id}"
        ),
        discord.Color.green()
    )


@bot.tree.command(
    name="unlinkroblox",
    description="Roblox fiók leválasztása"
)
async def unlinkroblox_slash(
    interaction: discord.Interaction
):

    data = load_data()

    links = data.setdefault(
        "roblox_links",
        {}
    )

    user_id = str(
        interaction.user.id
    )

    if user_id not in links:

        await interaction.response.send_message(
            "❌ Nincs Roblox fiók összekapcsolva.",
            ephemeral=True
        )

        return

    del links[user_id]

    save_data(data)

    await interaction.response.send_message(
        "✅ Roblox fiókod leválasztva.",
        ephemeral=True
    )


@bot.tree.command(
    name="robloxlink",
    description="Megmutatja a saját Roblox kapcsolatodat"
)
async def robloxlink_slash(
    interaction: discord.Interaction
):

    data = load_data()

    roblox_user_id = data.get(
        "roblox_links",
        {}
    ).get(
        str(interaction.user.id)
    )

    if not roblox_user_id:

        await interaction.response.send_message(
            (
                "❌ Nincs Roblox fiókod összekapcsolva.\n"
                "Használd: /linkroblox"
            ),
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        (
            "🎮 **Roblox kapcsolat**\n\n"
            f"**Roblox User ID:** {roblox_user_id}\n"
            f"**Discord:** {interaction.user.mention}"
        ),
        ephemeral=True
    )


# ============================================================
# PONT RENDSZER
# ============================================================

@bot.tree.command(
    name="pontok",
    description="Megmutatja egy felhasználó pontjait"
)
@app_commands.describe(
    member="A felhasználó, akinek megnézed a pontjait"
)
async def pontok_slash(
    interaction: discord.Interaction,
    member: discord.Member
):

    data = load_data()

    user_id = str(member.id)

    points = data.get(
        "points",
        {}
    ).get(
        user_id,
        0
    )

    embed = discord.Embed(
        title="⭐ Pontok",
        description=(
            f"{member.mention} pontjai: **{points}**"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.set_thumbnail(
        url=member_avatar(member)
    )

    embed.set_footer(
        text="Particle • Pont rendszer"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# PONT ADD
# ============================================================

@bot.tree.command(
    name="pont-add",
    description="Pont hozzáadása egy felhasználóhoz"
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    member="A felhasználó",
    amount="Hány pontot adjunk hozzá"
)
async def pont_add_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):

    if amount <= 0:

        await interaction.response.send_message(
            (
                "❌ A hozzáadandó pont mennyisége "
                "legalább **1** kell legyen."
            ),
            ephemeral=True
        )

        return

    data = load_data()

    data.setdefault(
        "points",
        {}
    )

    user_id = str(member.id)

    old_points = data[
        "points"
    ].get(
        user_id,
        0
    )

    new_points = old_points + amount

    data["points"][user_id] = new_points

    save_data(data)

    embed = discord.Embed(
        title="⭐ Pont hozzáadva",
        description=(
            f"**Felhasználó:** {member.mention}\n"
            f"**Hozzáadva:** +{amount} pont\n"
            f"**Régi pont:** {old_points}\n"
            f"**Új pont:** **{new_points}**"
        ),
        color=discord.Color.green()
    )

    embed.set_thumbnail(
        url=member_avatar(member)
    )

    embed.set_footer(
        text=f"Adta: {interaction.user.display_name}"
    )

    await interaction.response.send_message(
        embed=embed
    )

    await send_log(
        interaction.guild,
        "⭐ Pont hozzáadva",
        (
            f"**Felhasználó:** {member.mention}\n"
            f"**Mennyiség:** +{amount}\n"
            f"**Régi pont:** {old_points}\n"
            f"**Új pont:** {new_points}\n"
            f"**Admin:** {interaction.user.mention}"
        ),
        discord.Color.green()
    )


# ============================================================
# PONT REMOVE
# ============================================================

@bot.tree.command(
    name="pont-remove",
    description="Pont levonása egy felhasználótól"
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    member="A felhasználó",
    amount="Hány pontot vonjunk le"
)
async def pont_remove_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):

    if amount <= 0:

        await interaction.response.send_message(
            (
                "❌ A levonandó pont mennyisége "
                "legalább **1** kell legyen."
            ),
            ephemeral=True
        )

        return

    data = load_data()

    data.setdefault(
        "points",
        {}
    )

    user_id = str(member.id)

    old_points = data[
        "points"
    ].get(
        user_id,
        0
    )

    new_points = max(
        0,
        old_points - amount
    )

    removed_points = old_points - new_points

    data["points"][user_id] = new_points

    save_data(data)

    embed = discord.Embed(
        title="⭐ Pont levonva",
        description=(
            f"**Felhasználó:** {member.mention}\n"
            f"**Levonva:** -{removed_points} pont\n"
            f"**Régi pont:** {old_points}\n"
            f"**Új pont:** **{new_points}**"
        ),
        color=discord.Color.orange()
    )

    embed.set_thumbnail(
        url=member_avatar(member)
    )

    embed.set_footer(
        text=(
            f"Levonást végezte: "
            f"{interaction.user.display_name}"
        )
    )

    await interaction.response.send_message(
        embed=embed
    )

    await send_log(
        interaction.guild,
        "⭐ Pont levonva",
        (
            f"**Felhasználó:** {member.mention}\n"
            f"**Mennyiség:** -{removed_points}\n"
            f"**Régi pont:** {old_points}\n"
            f"**Új pont:** {new_points}\n"
            f"**Admin:** {interaction.user.mention}"
        ),
        discord.Color.orange()
    )


# ============================================================
# TICKET CONTROL VIEW
# ============================================================

class TicketControlView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Ticket felvétele",
        style=discord.ButtonStyle.success,
        emoji="✋",
        custom_id="claim_ticket_btn"
    )
    async def claim_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        staff_role = discord.utils.get(
            interaction.guild.roles,
            name=STAFF_ROLE_NAME
        )

        has_permission = (
            interaction.user.guild_permissions.administrator
            or (
                staff_role in interaction.user.roles
                if staff_role
                else False
            )
        )

        if not has_permission:

            await interaction.response.send_message(
                (
                    "❌ Ezt a gombot csak a "
                    "**Staff** csapattagok használhatják!"
                ),
                ephemeral=True
            )

            return

        button.disabled = True

        button.label = (
            f"Kezeli: "
            f"{interaction.user.display_name}"
        )

        button.style = (
            discord.ButtonStyle.secondary
        )

        await interaction.response.edit_message(
            view=self
        )

        claim_embed = discord.Embed(
            title="✋ Ticket átvéve",
            description=(
                f"Ezt a ticketet **"
                f"{interaction.user.mention}** "
                "vette át!"
            ),
            color=discord.Color.from_rgb(
                0,
                200,
                150
            )
        )

        await interaction.channel.send(
            embed=claim_embed
        )

        await send_log(
            interaction.guild,
            "🎫 Ticket átvéve",
            (
                f"**Ticket:** "
                f"{interaction.channel.mention}\n"
                f"**Kezeli:** "
                f"{interaction.user.mention}"
            ),
            discord.Color.green()
        )

    @discord.ui.button(
        label="Bezárás",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="close_ticket_btn"
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            (
                "🔒 **A ticket 5 másodperc múlva "
                "lezárásra és törlésre kerül...**"
            )
        )

        await send_log(
            interaction.guild,
            "🔒 Ticket bezárása",
            (
                f"**Csatorna:** "
                f"{interaction.channel.name}\n"
                f"**Bezárta:** "
                f"{interaction.user.mention}"
            ),
            discord.Color.red()
        )

        await asyncio.sleep(5)

        try:
            await interaction.channel.delete()

        except Exception:
            pass


# ============================================================
# TICKET PANEL VIEW
# ============================================================

class TicketPanelView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    async def create_ticket_channel(
        self,
        interaction: discord.Interaction,
        category_name: str,
        emoji: str
    ):

        guild = interaction.guild
        user = interaction.user

        clean_category = (
            category_name
            .lower()
            .replace(" ", "-")
        )

        ticket_channel_name = (
            f"{clean_category}-"
            f"{user.name.lower()}"
        )

        existing_channel = discord.utils.get(
            guild.channels,
            name=ticket_channel_name
        )

        if existing_channel:

            await interaction.response.send_message(
                (
                    "⚠️ Már van egy nyitott ticketed ebben "
                    f"a kategóriában: "
                    f"{existing_channel.mention}"
                ),
                ephemeral=True
            )

            return

        staff_role = discord.utils.get(
            guild.roles,
            name=STAFF_ROLE_NAME
        )

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(
                    read_messages=False
                ),

            user:
                discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True
                ),

            guild.me:
                discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )
        }

        if staff_role:

            overwrites[staff_role] = (
                discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )
            )

        channel = await guild.create_text_channel(
            name=ticket_channel_name,
            overwrites=overwrites
        )

        await interaction.response.send_message(
            (
                f"✅ Ticket sikeresen létrehozva: "
                f"{channel.mention}"
            ),
            ephemeral=True
        )

        embed = discord.Embed(
            title=(
                f"{emoji} Gaming Community | "
                f"{category_name}"
            ),
            description=(
                f"Üdvözlünk **{user.mention}**!\n\n"
                "Kérjük, írd le részletesen a "
                "kérésedet/problémádat, és a "
                "**Staff csapat** hamarosan válaszolni fog.\n\n"
                "🌊 *Köszönjük, hogy kapcsolatba léptél "
                "velünk!*"
            ),
            color=discord.Color.from_rgb(
                0,
                174,
                239
            )
        )

        if guild.icon:
            embed.set_thumbnail(
                url=guild.icon.url
            )

        embed.set_footer(
            text="Gaming Community System • Ticket rendszer"
        )

        staff_ping = (
            staff_role.mention
            if staff_role
            else ""
        )

        await channel.send(
            content=(
                f"{user.mention} "
                f"{staff_ping}"
            ),
            embed=embed,
            view=TicketControlView()
        )

        await send_log(
            guild,
            "🎫 Új ticket",
            (
                f"**Felhasználó:** {user.mention}\n"
                f"**Kategória:** {category_name}\n"
                f"**Csatorna:** {channel.mention}"
            ),
            discord.Color.blue()
        )

    @discord.ui.button(
        label="Tagfelvétel",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="t_tagfelvetel"
    )
    async def tagfelvetel(
        self,
        interaction,
        button
    ):

        await self.create_ticket_channel(
            interaction,
            "Tagfelvétel",
            "📝"
        )

    @discord.ui.button(
        label="Bug Jelentése",
        style=discord.ButtonStyle.primary,
        emoji="🐛",
        custom_id="t_bug"
    )
    async def bug(
        self,
        interaction,
        button
    ):

        await self.create_ticket_channel(
            interaction,
            "Bug-Jelentés",
            "🐛"
        )

    @discord.ui.button(
        label="Játékos Jelentése",
        style=discord.ButtonStyle.primary,
        emoji="🚨",
        custom_id="t_player"
    )
    async def player(
        self,
        interaction,
        button
    ):

        await self.create_ticket_channel(
            interaction,
            "Játékos-Jelentés",
            "🚨"
        )

    @discord.ui.button(
        label="Partnerség",
        style=discord.ButtonStyle.primary,
        emoji="🤝",
        custom_id="t_partner"
    )
    async def partner(
        self,
        interaction,
        button
    ):

        await self.create_ticket_channel(
            interaction,
            "Partnerség",
            "🤝"
        )

    @discord.ui.button(
        label="Egyéb",
        style=discord.ButtonStyle.secondary,
        emoji="❓",
        custom_id="t_egyeb"
    )
    async def egyeb(
        self,
        interaction,
        button
    ):

        await self.create_ticket_channel(
            interaction,
            "Egyéb",
            "❓"
        )


# ============================================================
# ÖTLET RENDSZER
# ============================================================

class IdeaModal(
    discord.ui.Modal,
    title="💡 Új ötlet beküldése"
):

    idea = discord.ui.TextInput(
        label="Mi az ötleted?",
        placeholder="Írd le részletesen az ötletedet...",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=2000,
        required=True
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        data = load_data()

        settings = data.get(
            "guild_settings",
            {}
        ).get(
            str(interaction.guild.id),
            {}
        )

        channel_id = settings.get(
            "idea_channel_id"
        )

        if not channel_id:

            await interaction.response.send_message(
                (
                    "❌ Az ötlet csatorna nincs beállítva. "
                    "Egy admin állítsa be a /setup paranccsal!"
                ),
                ephemeral=True
            )

            return

        channel = interaction.guild.get_channel(
            int(channel_id)
        )

        if channel is None:

            await interaction.response.send_message(
                "❌ A beállított ötlet csatorna nem található.",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="💡 Új ötlet",
            color=discord.Color.from_rgb(
                0,
                174,
                239
            ),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="👤 Beküldő",
            value=(
                f"{interaction.user.mention} "
                f"({interaction.user.id})"
            ),
            inline=False
        )

        embed.add_field(
            name="💡 Ötlet",
            value=str(self.idea.value),
            inline=False
        )

        embed.set_thumbnail(
            url=member_avatar(
                interaction.user
            )
        )

        embed.set_footer(
            text="Particle • Ötlet rendszer"
        )

        try:

            await channel.send(
                embed=embed
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                (
                    "❌ Nem tudok üzenetet küldeni a "
                    "beállított ötlet csatornába."
                ),
                ephemeral=True
            )

            return

        except Exception as e:

            print(
                f"[ERROR IDEA] {e}"
            )

            await interaction.response.send_message(
                "❌ Hiba történt az ötlet beküldésekor.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            (
                "✅ Az ötleted sikeresen elküldve! "
                "Köszönjük! 💡"
            ),
            ephemeral=True
        )

        await send_log(
            interaction.guild,
            "💡 Új ötlet beküldve",
            (
                f"**Beküldő:** {interaction.user.mention}\n"
                f"**Ötlet csatorna:** {channel.mention}\n"
                f"**Ötlet:** {self.idea.value}"
            ),
            discord.Color.blue()
        )


class IdeaPanelView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Ötletem van",
        style=discord.ButtonStyle.success,
        emoji="💡",
        custom_id="particle_idea_button"
    )
    async def idea_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            IdeaModal()
        )


# ============================================================
# TICKET PANEL PARANCS
# ============================================================

@bot.tree.command(
    name="ticketpanel",
    description="Kiküldi a Gaming Community ticket panelt"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def ticketpanel_slash(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="🎮 Gaming Community — TÁMOGATÁS ÉS TICKETEK",
        description=(
            "Miben segíthetünk? Válassz az alábbi "
            "kategóriák közül!\n\n"
            "📝 **Tagfelvétel**\n"
            "🐛 **Bug Jelentése**\n"
            "🚨 **Játékos Jelentése**\n"
            "🤝 **Partnerség**\n"
            "❓ **Egyéb**\n\n"
            "⚠️ *A felesleges vagy komolytalan "
            "ticketek nyitása szankciót vonhat maga után!*"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    if interaction.guild.icon:
        embed.set_thumbnail(
            url=interaction.guild.icon.url
        )

    embed.set_footer(
        text="Gaming Community System • Ticket rendszer"
    )

    await interaction.response.send_message(
        embed=embed,
        view=TicketPanelView()
    )


# ============================================================
# ÖTLET PANEL PARANCS
# ============================================================

@bot.tree.command(
    name="otlet-message",
    description="Kiküldi az ötletbeküldő panelt"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def otlet_message_slash(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="💡 ÖTLET RENDSZER",
        description=(
            "Van egy jó ötleted a szerverhez?\n"
            "Oszd meg velünk! Kattints az alábbi "
            "gombra, írd le az ötletedet, és a "
            "Particle elküldi azt a beállított "
            "ötletcsatornába.\n\n"
            "💡 **Ötletem van** — új ötlet beküldése"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    if interaction.guild.icon:
        embed.set_thumbnail(
            url=interaction.guild.icon.url
        )

    embed.set_footer(
        text="Particle • Ötlet rendszer"
    )

    await interaction.response.send_message(
        embed=embed,
        view=IdeaPanelView()
    )


# ============================================================
# SETUP
# ============================================================

@bot.tree.command(
    name="setup",
    description="Bot szerverbeállításainak módosítása"
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    autorole="Automatikusan kiosztandó rang",
    welcome_channel="Üdvözlő üzenetek csatornája",
    leave_channel="Távozási üzenetek csatornája",
    log_channel="Minden log csatornája",
    idea_channel="Ide küldi a bot az ötleteket"
)
async def setup_slash(
    interaction: discord.Interaction,
    autorole: discord.Role = None,
    welcome_channel: discord.TextChannel = None,
    leave_channel: discord.TextChannel = None,
    log_channel: discord.TextChannel = None,
    idea_channel: discord.TextChannel = None
):

    data = load_data()

    guild_id = str(
        interaction.guild.id
    )

    settings = data.setdefault(
        "guild_settings",
        {}
    ).setdefault(
        guild_id,
        {}
    )

    if autorole is not None:
        settings["autorole_id"] = autorole.id

    if welcome_channel is not None:
        settings["welcome_channel_id"] = (
            welcome_channel.id
        )

    if leave_channel is not None:
        settings["leave_channel_id"] = (
            leave_channel.id
        )

    if log_channel is not None:
        settings["log_channel_id"] = (
            log_channel.id
        )

    if idea_channel is not None:
        settings["idea_channel_id"] = (
            idea_channel.id
        )

    save_data(data)

    autorole_obj = None

    if settings.get("autorole_id"):
        autorole_obj = interaction.guild.get_role(
            int(settings["autorole_id"])
        )

    autorole_text = (
        autorole_obj.mention
        if autorole_obj
        else "Nincs beállítva"
    )

    welcome_obj = None

    if settings.get("welcome_channel_id"):
        welcome_obj = interaction.guild.get_channel(
            int(settings["welcome_channel_id"])
        )

    welcome_text = (
        welcome_obj.mention
        if welcome_obj
        else "Nincs beállítva"
    )

    leave_obj = None

    if settings.get("leave_channel_id"):
        leave_obj = interaction.guild.get_channel(
            int(settings["leave_channel_id"])
        )

    leave_text = (
        leave_obj.mention
        if leave_obj
        else "Nincs beállítva"
    )

    log_obj = None

    if settings.get("log_channel_id"):
        log_obj = interaction.guild.get_channel(
            int(settings["log_channel_id"])
        )

    log_text = (
        log_obj.mention
        if log_obj
        else "Nincs beállítva"
    )

    idea_obj = None

    if settings.get("idea_channel_id"):
        idea_obj = interaction.guild.get_channel(
            int(settings["idea_channel_id"])
        )

    idea_text = (
        idea_obj.mention
        if idea_obj
        else "Nincs beállítva"
    )

    embed = discord.Embed(
        title="⚙️ Particle • Szerver beállítás",
        description=(
            "A beállítások sikeresen mentve!\n"
            "A korábbi beállítások megmaradnak, "
            "ha egy mezőt nem adsz meg."
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.add_field(
        name="🛡️ Autorole",
        value=autorole_text,
        inline=False
    )

    embed.add_field(
        name="👋 Üdvözlő csatorna",
        value=welcome_text,
        inline=False
    )

    embed.add_field(
        name="🚪 Távozási csatorna",
        value=leave_text,
        inline=False
    )

    embed.add_field(
        name="📋 Log csatorna",
        value=log_text,
        inline=False
    )

    embed.add_field(
        name="💡 Ötlet csatorna",
        value=idea_text,
        inline=False
    )

    embed.set_footer(
        text="Particle • /setup"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

    await send_log(
        interaction.guild,
        "⚙️ Szerver beállítás módosítva",
        (
            f"**Beállította:** "
            f"{interaction.user.mention}\n"
            f"**Autorole:** {autorole_text}\n"
            f"**Welcome:** {welcome_text}\n"
            f"**Leave:** {leave_text}\n"
            f"**Log:** {log_text}\n"
            f"**Ötlet:** {idea_text}"
        ),
        discord.Color.blue()
    )


# ============================================================
# EMBED KÜLDÉS
# ============================================================

@bot.tree.command(
    name="embed",
    description="Egyedi embed üzenet küldése"
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    title="Az embed címe",
    description="Az embed szövege",
    color="Embed színe HEX formátumban, pl. #00AEEF"
)
async def embed_slash(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: str = "#00AEEF"
):

    color = color.replace(
        "#",
        ""
    ).strip()

    if len(color) != 6:

        await interaction.response.send_message(
            (
                "❌ A színnek 6 karakteres HEX "
                "kódnak kell lennie!\n"
                "Példa: `#00AEEF`"
            ),
            ephemeral=True
        )

        return

    try:
        color_value = int(
            color,
            16
        )

    except ValueError:

        await interaction.response.send_message(
            (
                "❌ Érvénytelen HEX szín!\n"
                "Példa: `#00AEEF`"
            ),
            ephemeral=True
        )

        return

    if len(title) > 256:

        await interaction.response.send_message(
            "❌ Az embed címe maximum 256 karakter lehet.",
            ephemeral=True
        )

        return

    if len(description) > 4096:

        await interaction.response.send_message(
            "❌ Az embed szövege maximum 4096 karakter lehet.",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color_value,
        timestamp=datetime.utcnow()
    )

    embed.set_footer(
        text=(
            f"Particle • Küldte: "
            f"{interaction.user.display_name}"
        )
    )

    await interaction.response.send_message(
        "✅ Embed sikeresen elküldve!",
        ephemeral=True
    )

    await interaction.channel.send(
        embed=embed
    )


# ============================================================
# MEMBER JOIN
# ============================================================

@bot.event
async def on_member_join(member):

    data = load_data()

    settings = data.get(
        "guild_settings",
        {}
    ).get(
        str(member.guild.id),
        {}
    )

    # AUTOROLE
    role_id = settings.get(
        "autorole_id"
    )

    if role_id:

        role = member.guild.get_role(
            int(role_id)
        )

        if role:

            try:

                await member.add_roles(
                    role,
                    reason="Particle automatikus rang"
                )

                await send_log(
                    member.guild,
                    "🛡️ Autorole kiosztva",
                    (
                        f"**Tag:** {member.mention}\n"
                        f"**Rang:** {role.mention}"
                    ),
                    discord.Color.green()
                )

            except Exception as e:

                print(
                    f"{Fore.RED}"
                    f"[ERROR AUTOROLE]"
                    f"{Style.RESET_ALL} {e}"
                )

    # WELCOME
    channel_id = settings.get(
        "welcome_channel_id"
    )

    channel = (
        member.guild.get_channel(
            int(channel_id)
        )
        if channel_id
        else None
    )

    if channel:

        embed = discord.Embed(
            title="👋 Üdvözlünk!",
            description=(
                f"Szia {member.mention}! "
                f"Örülünk, hogy csatlakoztál a "
                f"**{member.guild.name}** szerverhez! 🎉"
            ),
            color=discord.Color.from_rgb(
                0,
                174,
                239
            ),
            timestamp=datetime.utcnow()
        )

        embed.set_thumbnail(
            url=member_avatar(member)
        )

        embed.set_footer(
            text="Particle • Üdvözlő rendszer"
        )

        try:

            await channel.send(
                embed=embed
            )

        except Exception as e:

            print(
                f"{Fore.RED}"
                f"[ERROR WELCOME]"
                f"{Style.RESET_ALL} {e}"
            )

    await send_log(
        member.guild,
        "📥 Tag csatlakozott",
        (
            f"**Tag:** {member.mention}\n"
            f"**ID:** {member.id}"
        ),
        discord.Color.green()
    )


# ============================================================
# MEMBER REMOVE
# ============================================================

@bot.event
async def on_member_remove(member):

    data = load_data()

    settings = data.get(
        "guild_settings",
        {}
    ).get(
        str(member.guild.id),
        {}
    )

    channel_id = settings.get(
        "leave_channel_id"
    )

    channel = (
        member.guild.get_channel(
            int(channel_id)
        )
        if channel_id
        else None
    )

    if channel:

        embed = discord.Embed(
            title="👋 Egy tag távozott",
            description=(
                f"**{member.display_name}** "
                "elhagyta a szervert. 😢"
            ),
            color=discord.Color.from_rgb(
                120,
                120,
                120
            ),
            timestamp=datetime.utcnow()
        )

        embed.set_thumbnail(
            url=member_avatar(member)
        )

        embed.set_footer(
            text="Particle • Távozási rendszer"
        )

        try:

            await channel.send(
                embed=embed
            )

        except Exception as e:

            print(
                f"{Fore.RED}"
                f"[ERROR LEAVE]"
                f"{Style.RESET_ALL} {e}"
            )

    await send_log(
        member.guild,
        "📤 Tag távozott",
        (
            f"**Tag:** {member}\n"
            f"**ID:** {member.id}"
        ),
        discord.Color.orange()
    )


# ============================================================
# DISCORD ROLE -> ROBLOX ROLE
# ============================================================

@bot.event
async def on_member_update(
    before,
    after
):

    if before.roles == after.roles:
        return

    added_roles = [
        role
        for role in after.roles
        if role not in before.roles
    ]

    removed_roles = [
        role
        for role in before.roles
        if role not in after.roles
    ]

    # ROLE HOZZÁADÁSA
    for role in added_roles:

        if role.id in ROBLOX_ROLE_BINDS:

            await sync_roblox_role(
                after,
                role
            )

    # ROLE ELVÉTELE
    if (
        ROBLOX_DEFAULT_ROLE_ID
        and removed_roles
    ):

        had_bound_role_removed = any(
            role.id in ROBLOX_ROLE_BINDS
            for role in removed_roles
        )

        if had_bound_role_removed:

            data = load_data()

            roblox_user_id = data.get(
                "roblox_links",
                {}
            ).get(
                str(after.id)
            )

            if roblox_user_id:

                success, message = (
                    await set_roblox_rank(
                        roblox_user_id,
                        ROBLOX_DEFAULT_ROLE_ID
                    )
                )

                if success:

                    await send_log(
                        after.guild,
                        "🔄 Roblox rank visszaállítva",
                        (
                            f"**Tag:** {after.mention}\n"
                            f"**Roblox User ID:** "
                            f"{roblox_user_id}\n"
                            f"**Új Roblox Role ID:** "
                            f"{ROBLOX_DEFAULT_ROLE_ID}"
                        ),
                        discord.Color.orange()
                    )

                else:

                    print(
                        f"{Fore.RED}"
                        f"[ROBLOX ERROR]"
                        f"{Style.RESET_ALL} "
                        f"{message}"
                    )


# ============================================================
# HELP
# ============================================================

@bot.tree.command(
    name="help",
    description="A bot összes slash parancsa"
)
async def help_slash(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="📚 Particle Bot • Parancsok",
        description=(
            "A bot elérhető slash parancsai:"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.add_field(
        name="🎮 Roblox",
        value=(
            "/linkroblox — Roblox fiók összekötése\n"
            "/unlinkroblox — Roblox kapcsolat törlése\n"
            "/robloxlink — Roblox kapcsolat megtekintése"
        ),
        inline=False
    )

    embed.add_field(
        name="⭐ Pont rendszer",
        value=(
            "/pontok — Felhasználó pontjainak megtekintése\n"
            "/pont-add — Pont hozzáadása *(Admin)*\n"
            "/pont-remove — Pont levonása *(Admin)*"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Beállítás",
        value=(
            "/setup — Bot beállítása\n"
            "/otlet-message — Ötletpanel kiküldése"
        ),
        inline=False
    )

    embed.add_field(
        name="🎟️ Ticket",
        value=(
            "/ticketpanel — Ticket panel"
        ),
        inline=False
    )

    embed.add_field(
        name="🛡️ Moderáció",
        value=(
            "/clear\n"
            "/kick\n"
            "/ban\n"
            "/unban\n"
            "/timeout\n"
            "/unmute\n"
            "/lock\n"
            "/unlock\n"
            "/warn\n"
            "/warns\n"
            "/unwarn"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Utility",
        value=(
            "/ping\n"
            "/status\n"
            "/userinfo\n"
            "/serverinfo\n"
            "/avatar\n"
            "/say\n"
            "/poll\n"
            "/embed *(Admin)*"
        ),
        inline=False
    )

    embed.add_field(
        name="🎉 Giveaway",
        value="/gcreate",
        inline=False
    )

    embed.add_field(
        name="🎮 Fun",
        value=(
            "/coinflip\n"
            "/hug\n"
            "/slap\n"
            "/csok"
        ),
        inline=False
    )

    embed.set_footer(
        text="Particle System"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# UTILITY
# ============================================================

@bot.tree.command(
    name="ping",
    description="Bot késleltetésének lekérése"
)
async def ping_slash(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        embed=discord.Embed(
            title="📳 Pong!",
            description=(
                f"Késleltetés: "
                f"**{round(bot.latency * 1000)}ms**"
            ),
            color=discord.Color.green()
        )
    )


@bot.tree.command(
    name="say",
    description="Üzenet küldése a bot nevében"
)
async def say_slash(
    interaction: discord.Interaction,
    message: str
):

    await interaction.response.send_message(
        "✅ Üzenet elküldve!",
        ephemeral=True
    )

    await interaction.channel.send(
        message
    )

    await send_log(
        interaction.guild,
        "💬 Say használva",
        (
            f"**Felhasználó:** "
            f"{interaction.user.mention}\n"
            f"**Üzenet:** {message}"
        ),
        discord.Color.blue()
    )


@bot.tree.command(
    name="avatar",
    description="Felhasználó profilképének lekérése"
)
async def avatar_slash(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    member = (
        member
        or interaction.user
    )

    embed = discord.Embed(
        title=(
            f"🖼️ {member.display_name} "
            "profilképe"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.set_image(
        url=member_avatar(member)
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="userinfo",
    description="Részletes felhasználói információ"
)
async def userinfo_slash(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    member = (
        member
        or interaction.user
    )

    roles = [
        role.mention
        for role in member.roles[1:]
    ]

    if not roles:
        roles = [
            "Nincs rangja"
        ]

    embed = discord.Embed(
        title=(
            f"👤 Felhasználói Infó - "
            f"{member}"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.set_thumbnail(
        url=member_avatar(member)
    )

    embed.add_field(
        name="ID:",
        value=f"{member.id}",
        inline=True
    )

    embed.add_field(
        name="Fiók létrehozva:",
        value=member.created_at.strftime(
            "%Y.%m.%d %H:%M"
        ),
        inline=True
    )

    joined = (
        member.joined_at.strftime(
            "%Y.%m.%d %H:%M"
        )
        if member.joined_at
        else "Ismeretlen"
    )

    embed.add_field(
        name="Csatlakozott:",
        value=joined,
        inline=True
    )

    embed.add_field(
        name=f"Rangok ({len(roles)}):",
        value=", ".join(roles),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="serverinfo",
    description="Részletes szerverinformáció"
)
async def serverinfo_slash(
    interaction: discord.Interaction
):

    guild = interaction.guild

    embed = discord.Embed(
        title=(
            f"🏰 Szerver Infó - "
            f"{guild.name}"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    if guild.icon:
        embed.set_thumbnail(
            url=guild.icon.url
        )

    embed.add_field(
        name="Szerver ID:",
        value=f"{guild.id}",
        inline=True
    )

    embed.add_field(
        name="Tulajdonos:",
        value=(
            guild.owner.mention
            if guild.owner
            else "Ismeretlen"
        ),
        inline=True
    )

    embed.add_field(
        name="Tagok:",
        value=(
            f"👥 **{guild.member_count}**"
        ),
        inline=True
    )

    embed.add_field(
        name="Csatornák:",
        value=(
            f"💬 {len(guild.text_channels)} szöveg\n"
            f"🔊 {len(guild.voice_channels)} hang"
        ),
        inline=True
    )

    embed.add_field(
        name="Rangok:",
        value=(
            f"📜 {len(guild.roles)}"
        ),
        inline=True
    )

    embed.add_field(
        name="Létrehozva:",
        value=guild.created_at.strftime(
            "%Y.%m.%d"
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


@bot.tree.command(
    name="poll",
    description="Gyors szavazás indítása"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def poll_slash(
    interaction: discord.Interaction,
    question: str
):

    await interaction.response.send_message(
        "✅ Szavazás kiírva!",
        ephemeral=True
    )

    embed = discord.Embed(
        title="📊 Szavazás",
        description=question,
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.set_footer(
        text=(
            f"Indította: "
            f"{interaction.user.display_name}"
        )
    )

    poll_msg = await interaction.channel.send(
        embed=embed
    )

    await poll_msg.add_reaction("👍")
    await poll_msg.add_reaction("👎")


# ============================================================
# CLEAR
# ============================================================

@bot.tree.command(
    name="clear",
    description="Megadott számú üzenet törlése"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
async def clear_slash(
    interaction: discord.Interaction,
    amount: int = 5
):

    if amount < 1:

        await interaction.response.send_message(
            "❌ Legalább 1 üzenetet adj meg.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(
        embed=discord.Embed(
            description=(
                f"🧹 **{len(deleted)}** "
                "üzenet törölve!"
            ),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

    await send_log(
        interaction.guild,
        "🧹 Üzenetek törölve",
        (
            f"**Moderátor:** "
            f"{interaction.user.mention}\n"
            f"**Csatorna:** "
            f"{interaction.channel.mention}\n"
            f"**Mennyiség:** {len(deleted)}"
        ),
        discord.Color.orange()
    )


# ============================================================
# KICK
# ============================================================

@bot.tree.command(
    name="kick",
    description="Felhasználó kirúgása"
)
@app_commands.checks.has_permissions(
    kick_members=True
)
async def kick_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Nincs megadva"
):

    await member.kick(
        reason=reason
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"👞 **{member}** ki lett rúgva!\n"
                f"**Indok:** {reason}"
            ),
            color=discord.Color.orange()
        )
    )

    await send_log(
        interaction.guild,
        "👞 Tag kirúgva",
        (
            f"**Tag:** {member}\n"
            f"**ID:** {member.id}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}\n"
            f"**Indok:** {reason}"
        ),
        discord.Color.orange()
    )


# ============================================================
# BAN
# ============================================================

@bot.tree.command(
    name="ban",
    description="Felhasználó kitiltása"
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def ban_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Nincs megadva"
):

    await member.ban(
        reason=reason
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"⛔ **{member}** ki lett tiltva!\n"
                f"**Indok:** {reason}"
            ),
            color=discord.Color.red()
        )
    )

    await send_log(
        interaction.guild,
        "⛔ Tag kitiltva",
        (
            f"**Tag:** {member}\n"
            f"**ID:** {member.id}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}\n"
            f"**Indok:** {reason}"
        ),
        discord.Color.red()
    )


# ============================================================
# UNBAN
# ============================================================

@bot.tree.command(
    name="unban",
    description="Felhasználó kitiltásának feloldása ID alapján"
)
@app_commands.checks.has_permissions(
    ban_members=True
)
async def unban_slash(
    interaction: discord.Interaction,
    user_id: str
):

    try:

        user = await bot.fetch_user(
            int(user_id)
        )

        await interaction.guild.unban(
            user
        )

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ **{user.name}** tiltása "
                    "feloldva!"
                ),
                color=discord.Color.green()
            )
        )

        await send_log(
            interaction.guild,
            "✅ Ban feloldva",
            (
                f"**Felhasználó:** {user}\n"
                f"**ID:** {user.id}\n"
                f"**Moderátor:** "
                f"{interaction.user.mention}"
            ),
            discord.Color.green()
        )

    except Exception:

        await interaction.response.send_message(
            (
                "❌ Nem található kitiltott "
                "felhasználó ezzel az ID-val!"
            ),
            ephemeral=True
        )


# ============================================================
# TIMEOUT
# ============================================================

@bot.tree.command(
    name="timeout",
    description="Felhasználó timeoutolása percben"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def timeout_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "Nincs megadva"
):

    if minutes <= 0:

        await interaction.response.send_message(
            (
                "❌ A timeout ideje legalább "
                "1 perc legyen."
            ),
            ephemeral=True
        )

        return

    duration = timedelta(
        minutes=minutes
    )

    await member.timeout(
        duration,
        reason=reason
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"🔇 **{member.mention}** némítva lett "
                f"**{minutes}** percre.\n"
                f"**Indok:** {reason}"
            ),
            color=discord.Color.orange()
        )
    )

    await send_log(
        interaction.guild,
        "🔇 Timeout",
        (
            f"**Tag:** {member.mention}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}\n"
            f"**Idő:** {minutes} perc\n"
            f"**Indok:** {reason}"
        ),
        discord.Color.orange()
    )


# ============================================================
# UNMUTE
# ============================================================

@bot.tree.command(
    name="unmute",
    description="Felhasználó timeoutjának feloldása"
)
@app_commands.checks.has_permissions(
    moderate_members=True
)
async def unmute_slash(
    interaction: discord.Interaction,
    member: discord.Member
):

    await member.timeout(
        None
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"🔊 **{member.mention}** némítása "
                "feloldva!"
            ),
            color=discord.Color.green()
        )
    )

    await send_log(
        interaction.guild,
        "🔊 Timeout feloldva",
        (
            f"**Tag:** {member.mention}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}"
        ),
        discord.Color.green()
    )


# ============================================================
# LOCK
# ============================================================

@bot.tree.command(
    name="lock",
    description="Csatorna lezárása"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def lock_slash(
    interaction: discord.Interaction
):

    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=False
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description="🔒 **A csatorna lezárva!**",
            color=discord.Color.red()
        )
    )

    await send_log(
        interaction.guild,
        "🔒 Csatorna lezárva",
        (
            f"**Csatorna:** "
            f"{interaction.channel.mention}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}"
        ),
        discord.Color.red()
    )


# ============================================================
# UNLOCK
# ============================================================

@bot.tree.command(
    name="unlock",
    description="Csatorna feloldása"
)
@app_commands.checks.has_permissions(
    manage_channels=True
)
async def unlock_slash(
    interaction: discord.Interaction
):

    await interaction.channel.set_permissions(
        interaction.guild.default_role,
        send_messages=True
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            description="🔓 **A csatorna megnyitva!**",
            color=discord.Color.green()
        )
    )

    await send_log(
        interaction.guild,
        "🔓 Csatorna feloldva",
        (
            f"**Csatorna:** "
            f"{interaction.channel.mention}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}"
        ),
        discord.Color.green()
    )


# ============================================================
# WARN
# ============================================================

@bot.tree.command(
    name="warn",
    description="Figyelmeztetés adása egy tagnak"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
@app_commands.describe(
    member="A figyelmeztetendő felhasználó",
    reason="A figyelmeztetés indoka"
)
async def warn_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Nincs megadva"
):

    data = load_data()

    user_id = str(
        member.id
    )

    if user_id not in data["warns"]:
        data["warns"][user_id] = []

    warn_data = {
        "reason": reason,
        "by": interaction.user.name,
        "by_id": interaction.user.id,
        "date": datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        ),
        "revoked": False
    }

    data["warns"][user_id].append(
        warn_data
    )

    save_data(data)

    warn_count = len(
        data["warns"][user_id]
    )

    await interaction.response.send_message(
        embed=discord.Embed(
            title="⚠️ Figyelmeztetés",
            description=(
                f"**{member.mention}** "
                "figyelmeztetést kapott!\n\n"
                f"**Warn:** #{warn_count}\n"
                f"**Indok:** {reason}\n"
                f"**Állapot:** 🟢 Aktív"
            ),
            color=discord.Color.gold()
        )
    )

    await send_log(
        interaction.guild,
        "⚠️ Warn kiosztva",
        (
            f"**Tag:** {member.mention}\n"
            f"**Warn:** #{warn_count}\n"
            f"**Moderátor:** "
            f"{interaction.user.mention}\n"
            f"**Indok:** {reason}"
        ),
        discord.Color.gold()
    )


# ============================================================
# WARNS
# ============================================================

@bot.tree.command(
    name="warns",
    description="Egy tag figyelmeztetéseinek lekérése"
)
async def warns_slash(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    member = (
        member
        or interaction.user
    )

    data = load_data()

    user_id = str(
        member.id
    )

    if (
        user_id not in data["warns"]
        or not data["warns"][user_id]
    ):

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ **{member.mention}** "
                    "nem rendelkezik figyelmeztetéssel."
                ),
                color=discord.Color.green()
            )
        )

        return

    warns = data["warns"][user_id]

    active_count = sum(
        1
        for w in warns
        if not w.get(
            "revoked",
            False
        )
    )

    revoked_count = sum(
        1
        for w in warns
        if w.get(
            "revoked",
            False
        )
    )

    embed = discord.Embed(
        title=(
            f"⚠️ {member.display_name} "
            "figyelmeztetései"
        ),
        description=(
            f"**Összes:** {len(warns)}\n"
            f"🟢 **Aktív:** {active_count}\n"
            f"🔴 **Visszavonva:** {revoked_count}"
        ),
        color=discord.Color.gold()
    )

    for idx, w in enumerate(
        warns,
        1
    ):

        if w.get(
            "revoked",
            False
        ):

            value = (
                f"**Indok:** "
                f"{w.get('reason', 'Nincs megadva')}\n"
                f"**Adta:** "
                f"{w.get('by', 'Ismeretlen')}\n"
                f"**Dátum:** "
                f"{w.get('date', 'Ismeretlen')}\n\n"
                f"🔴 **VISSZAVONVA**\n"
                f"**Visszavonta:** "
                f"{w.get('revoked_by', 'Ismeretlen')}\n"
                f"**Visszavonás indoka:** "
                f"{w.get('revoked_reason', 'Nincs megadva')}\n"
                f"**Visszavonva:** "
                f"{w.get('revoked_date', 'Ismeretlen')}"
            )

        else:

            value = (
                f"**Indok:** "
                f"{w.get('reason', 'Nincs megadva')}\n"
                f"**Adta:** "
                f"{w.get('by', 'Ismeretlen')}\n"
                f"**Dátum:** "
                f"{w.get('date', 'Ismeretlen')}\n"
                f"🟢 **AKTÍV**"
            )

        embed.add_field(
            name=f"#{idx}. Figyelmeztetés",
            value=value,
            inline=False
        )

    embed.set_footer(
        text="Particle • Warn rendszer"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# UNWARN
# ============================================================

@bot.tree.command(
    name="unwarn",
    description="Egy meglévő figyelmeztetés visszavonása"
)
@app_commands.checks.has_permissions(
    manage_messages=True
)
@app_commands.describe(
    member="A felhasználó, akinek a warnját visszavonod",
    warn="A visszavonandó warn sorszáma",
    reason="Miért vonod vissza a warn-t?"
)
async def unwarn_slash(
    interaction: discord.Interaction,
    member: discord.Member,
    warn: int,
    reason: str
):

    data = load_data()

    user_id = str(
        member.id
    )

    if (
        user_id not in data["warns"]
        or not data["warns"][user_id]
    ):

        await interaction.response.send_message(
            (
                "❌ Ennek a felhasználónak nincs "
                "figyelmeztetése."
            ),
            ephemeral=True
        )

        return

    warns = data["warns"][user_id]

    if (
        warn < 1
        or warn > len(warns)
    ):

        await interaction.response.send_message(
            (
                f"❌ Érvénytelen warn sorszám!\n"
                f"Válassz **1 és {len(warns)}** között."
            ),
            ephemeral=True
        )

        return

    selected_warn = warns[
        warn - 1
    ]

    if selected_warn.get(
        "revoked",
        False
    ):

        await interaction.response.send_message(
            (
                f"❌ A **#{warn}. warn** "
                "már vissza lett vonva."
            ),
            ephemeral=True
        )

        return

    selected_warn["revoked"] = True

    selected_warn["revoked_by"] = (
        interaction.user.name
    )

    selected_warn["revoked_by_id"] = (
        interaction.user.id
    )

    selected_warn["revoked_reason"] = (
        reason
    )

    selected_warn["revoked_date"] = (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    )

    save_data(data)

    embed = discord.Embed(
        title="↩️ Figyelmeztetés visszavonva",
        description=(
            f"**Felhasználó:** {member.mention}\n"
            f"**Warn:** #{warn}\n\n"
            f"**Eredeti indok:** "
            f"{selected_warn.get('reason', 'Nincs megadva')}\n"
            f"**Visszavonás indoka:** {reason}\n"
            f"**Állapot:** 🔴 Visszavonva"
        ),
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(
        name="👮 Visszavonta",
        value=interaction.user.mention,
        inline=True
    )

    embed.add_field(
        name="📅 Visszavonás ideje",
        value=datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        ),
        inline=True
    )

    embed.set_footer(
        text="Particle • Warn rendszer"
    )

    await interaction.response.send_message(
        embed=embed
    )

    await send_log(
        interaction.guild,
        "↩️ Warn visszavonva",
        (
            f"**Tag:** {member.mention}\n"
            f"**Warn:** #{warn}\n"
            f"**Visszavonta:** "
            f"{interaction.user.mention}\n"
            f"**Eredeti indok:** "
            f"{selected_warn.get('reason', 'Nincs megadva')}\n"
            f"**Visszavonás indoka:** {reason}"
        ),
        discord.Color.green()
    )


# ============================================================
# GIVEAWAY
# ============================================================

@bot.tree.command(
    name="gcreate",
    description="Nyereményjáték indítása"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def gcreate_slash(
    interaction: discord.Interaction,
    seconds: int,
    winners: int,
    prize: str
):

    if seconds <= 0:

        await interaction.response.send_message(
            (
                "❌ Az időnek legalább "
                "1 másodpercnek kell lennie."
            ),
            ephemeral=True
        )

        return

    if winners <= 0:

        await interaction.response.send_message(
            (
                "❌ Legalább 1 nyertes kell."
            ),
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        (
            "✅ Nyereményjáték sikeresen elindítva!"
        ),
        ephemeral=True
    )

    embed = discord.Embed(
        title="🎉 NYEREMÉNYJÁTÉK 🎉",
        description=(
            f"**Nyeremény:** {prize}\n"
            f"**Nyertesek:** {winners}\n"
            f"**Időtartam:** {seconds} másodperc\n\n"
            "Kattints a 🎉 reakcióra!"
        ),
        color=discord.Color.from_rgb(
            0,
            174,
            239
        )
    )

    embed.set_footer(
        text="Particle Giveaways"
    )

    msg = await interaction.channel.send(
        embed=embed
    )

    await msg.add_reaction(
        "🎉"
    )

    await send_log(
        interaction.guild,
        "🎉 Giveaway indult",
        (
            f"**Indította:** "
            f"{interaction.user.mention}\n"
            f"**Nyeremény:** {prize}\n"
            f"**Nyertesek:** {winners}\n"
            f"**Idő:** {seconds} másodperc"
        ),
        discord.Color.blue()
    )

    await asyncio.sleep(
        seconds
    )

    try:

        new_msg = await interaction.channel.fetch_message(
            msg.id
        )

    except Exception:
        return

    reaction = discord.utils.get(
        new_msg.reactions,
        emoji="🎉"
    )

    if reaction is None:

        await interaction.channel.send(
            "⚠️ Nem érkezett jelentkező."
        )

        return

    users = [
        user
        async for user in reaction.users()
        if not user.bot
    ]

    if len(users) < winners:

        await interaction.channel.send(
            (
                "⚠️ Nincs elég jelentkező "
                f"a nyereményjátékra! "
                f"Szükséges: **{winners}**"
            )
        )

        return

    winner_list = random.sample(
        users,
        winners
    )

    winners_str = ", ".join(
        user.mention
        for user in winner_list
    )

    await interaction.channel.send(
        embed=discord.Embed(
            title="🎉 Gratulálunk!",
            description=(
                f"**Nyeremény:** {prize}\n\n"
                f"**Győztesek:** {winners_str}"
            ),
            color=discord.Color.green()
        )
    )


# ============================================================
# FUN
# ============================================================

@bot.tree.command(
    name="coinflip",
    description="Pénzfeldobás"
)
async def coinflip_slash(
    interaction: discord.Interaction
):

    await interaction.response.send_message(
        embed=discord.Embed(
            title="🪙 Pénzfeldobás",
            description=(
                f"Eredmény: **"
                f"{random.choice(['Fej', 'Írás'])}"
                "**"
            ),
            color=discord.Color.gold()
        )
    )


@bot.tree.command(
    name="hug",
    description="Ölelés küldése"
)
async def hug_slash(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"🤗 **{interaction.user.mention}** "
                f"megölelte: **{member.mention}**!"
            ),
            color=discord.Color.from_rgb(
                255,
                105,
                180
            )
        )
    )


@bot.tree.command(
    name="slap",
    description="Pofon adása"
)
async def slap_slash(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"🖐️ **{interaction.user.mention}** "
                f"felképelte: **{member.mention}**!"
            ),
            color=discord.Color.red()
        )
    )


@bot.tree.command(
    name="csok",
    description="Puszi küldése"
)
async def csok_slash(
    interaction: discord.Interaction,
    member: discord.Member
):

    await interaction.response.send_message(
        embed=discord.Embed(
            description=(
                f"💋 **{interaction.user.mention}** "
                f"adott egy puszit neki: "
                f"**{member.mention}**!"
            ),
            color=discord.Color.from_rgb(
                255,
                182,
                193
            )
        )
    )


# ============================================================
# MINECRAFT SZERVER STATUS
# ============================================================

async def get_minecraft_server_status():
    """
    Lekéri a Minecraft szerver aktuális állapotát
    a mcsrvstat.us API-n keresztül.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                MINECRAFT_STATUS_URL,
                headers={
                    "User-Agent": "Particle-Discord-Bot/1.0"
                }
            ) as response:

                if response.status != 200:
                    return {
                        "online": False,
                        "error": f"API HTTP {response.status}"
                    }

                data = await response.json()

        if not data.get("online", False):
            return {
                "online": False,
                "error": None
            }

        players = data.get("players") or {}

        motd = data.get("motd") or {}
        motd_clean = motd.get("clean") or []
        if isinstance(motd_clean, list):
            motd_text = " ".join(
                str(line) for line in motd_clean
            ).strip()
        else:
            motd_text = str(motd_clean).strip()

        return {
            "online": True,
            "players_online": players.get("online", 0),
            "players_max": players.get("max", 0),
            "version": data.get("version", "Ismeretlen"),
            "motd": motd_text,
            "error": None
        }

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return {
            "online": False,
            "error": f"Kapcsolati hiba: {e}"
        }

    except Exception as e:
        return {
            "online": False,
            "error": f"Ismeretlen hiba: {e}"
        }


def build_minecraft_status_embed(status, previous_state=None):
    """
    Elkészíti a /status embedet.
    A previous_state tartalmazza az utolsó ismert állapotot
    és az állapotváltás időpontját.
    """
    now = datetime.utcnow()

    if status.get("online"):
        color = discord.Color.green()
        status_text = "🟢 **ONLINE**"
    else:
        color = discord.Color.red()
        status_text = "🔴 **OFFLINE**"

    embed = discord.Embed(
        title="🌊 AquaZone • Szerver státusz",
        description=(
            f"**Szerver:** `{MINECRAFT_SERVER_IP}`\n\n"
            f"**Állapot:** {status_text}"
        ),
        color=color,
        timestamp=now
    )

    if status.get("online"):
        embed.add_field(
            name="👥 Játékosok",
            value=(
                f"**{status.get('players_online', 0)}**"
                f"/"
                f"**{status.get('players_max', 0)}**"
            ),
            inline=True
        )

        embed.add_field(
            name="🧩 Verzió",
            value=str(status.get("version", "Ismeretlen")),
            inline=True
        )

        if status.get("motd"):
            motd = status["motd"]
            if len(motd) > 1024:
                motd = motd[:1021] + "..."

            embed.add_field(
                name="📜 MOTD",
                value=motd,
                inline=False
            )

    # Utolsó állapotváltás
    if previous_state:
        state_since = previous_state.get("state_since")
        if state_since:
            if status.get("online"):
                transition_text = (
                    f"🟢 Online: <t:{int(state_since.timestamp())}:R>"
                )
            else:
                transition_text = (
                    f"🔴 Offline: <t:{int(state_since.timestamp())}:R>"
                )

            embed.add_field(
                name="⏱️ Állapot ideje",
                value=transition_text,
                inline=False
            )

    embed.add_field(
        name="🔄 Következő frissítés",
        value=f"<t:{int((now + timedelta(seconds=STATUS_REFRESH_SECONDS)).timestamp())}:R>",
        inline=False
    )

    if status.get("error"):
        embed.add_field(
            name="⚠️ Ellenőrzési információ",
            value=(
                "A szerver státuszának lekérése közben hiba történt. "
                "A következő frissítésnél újra próbálom."
            ),
            inline=False
        )

    embed.set_footer(
        text="Particle • AquaZone Status • Frissítés: 10 percenként"
    )

    return embed


async def update_status_message(
    guild_id,
    channel_id,
    message_id
):
    """
    A /status üzenetet 10 percenként frissíti.
    """
    key = (guild_id, message_id)

    try:
        while True:
            status = await get_minecraft_server_status()
            now = datetime.utcnow()

            previous = status_states.get(guild_id)

            # Első mérés vagy állapotváltás esetén új időpontot mentünk.
            if previous is None:
                state_since = now
            elif previous.get("online") != status.get("online"):
                state_since = now
            else:
                state_since = previous.get("state_since", now)

            state = {
                "online": status.get("online", False),
                "state_since": state_since
            }

            status_states[guild_id] = state

            channel = bot.get_channel(channel_id)

            if channel is None:
                return

            try:
                message = await channel.fetch_message(message_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):
                return

            try:
                await message.edit(
                    embed=build_minecraft_status_embed(
                        status,
                        state
                    )
                )
            except discord.HTTPException:
                return

            await asyncio.sleep(STATUS_REFRESH_SECONDS)

    except asyncio.CancelledError:
        raise

    except Exception as e:
        print(
            f"{Fore.RED}"
            f"[STATUS ERROR]"
            f"{Style.RESET_ALL} {e}"
        )

    finally:
        status_tasks.pop(key, None)


@bot.tree.command(
    name="status",
    description="Megmutatja a play.aquazone.hu Minecraft szerver státuszát"
)
async def status_slash(
    interaction: discord.Interaction
):
    await interaction.response.defer()

    status = await get_minecraft_server_status()
    now = datetime.utcnow()

    previous = status_states.get(interaction.guild.id)

    if previous is None:
        state_since = now
    elif previous.get("online") != status.get("online"):
        state_since = now
    else:
        state_since = previous.get("state_since", now)

    state = {
        "online": status.get("online", False),
        "state_since": state_since
    }

    status_states[interaction.guild.id] = state

    embed = build_minecraft_status_embed(
        status,
        state
    )

    message = await interaction.followup.send(
        embed=embed,
        wait=True
    )

    key = (
        interaction.guild.id,
        message.id
    )

    # Ha ugyanahhoz az üzenethez már tartozna feladat, állítsuk le.
    old_task = status_tasks.get(key)

    if old_task and not old_task.done():
        old_task.cancel()

    status_tasks[key] = asyncio.create_task(
        update_status_message(
            interaction.guild.id,
            interaction.channel.id,
            message.id
        )
    )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    bot.add_view(
        TicketPanelView()
    )

    bot.add_view(
        TicketControlView()
    )

    bot.add_view(
        IdeaPanelView()
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"{Fore.GREEN}"
            f"[SLASH COMMANDS]"
            f"{Style.RESET_ALL} "
            f"Sikeresen szinkronizálva "
            f"{len(synced)} slash parancs!"
        )

    except Exception as e:

        print(
            f"{Fore.RED}"
            f"[SLASH ERROR]"
            f"{Style.RESET_ALL} {e}"
        )

    print(
        f"{Fore.GREEN}"
        f"[SUCCESS]"
        f"{Style.RESET_ALL} "
        f"Bejelentkezve mint: "
        f"{Fore.CYAN}"
        f"{bot.user.name}"
        f"{Style.RESET_ALL}"
    )

    print(
        f"{Fore.MAGENTA}"
        "====================================="
        f"{Style.RESET_ALL}"
    )

    if roblox_configured():

        print(
            f"{Fore.GREEN}"
            "[ROBLOX]"
            f"{Style.RESET_ALL} "
            "Open Cloud konfigurálva."
        )

    else:

        print(
            f"{Fore.YELLOW}"
            "[ROBLOX]"
            f"{Style.RESET_ALL} "
            "Open Cloud nincs konfigurálva."
        )

    await bot.change_presence(
        activity=discord.Game(
            name="Particle | /help"
        )
    )


# ============================================================
# HIBA KEZELÉS
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        message = (
            "❌ Nincs jogosultságod ehhez "
            "a parancshoz."
        )

    else:

        print(
            f"{Fore.RED}"
            f"[COMMAND ERROR]"
            f"{Style.RESET_ALL} "
            f"{error}"
        )

        message = (
            "❌ Hiba történt a parancs "
            "végrehajtása közben."
        )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception:
        pass


# ============================================================
# BOT INDÍTÁSA
# ============================================================

if __name__ == "__main__":

    if not TOKEN:

        print(
            f"{Fore.RED}"
            "[ERROR]"
            f"{Style.RESET_ALL} "
            "A DISCORD_TOKEN környezeti változó "
            "nincs beállítva!"
        )

    else:

        bot.run(TOKEN)
