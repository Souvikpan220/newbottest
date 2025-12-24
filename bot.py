import os
import time
import yaml
import requests
import discord
from discord import app_commands

# ==========================================================
# ENVIRONMENT VARIABLES (RAILWAY SECRETS)
# ==========================================================
TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_KEY")
API_URL = os.getenv("API_URL")

LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))

# Fail fast if secrets are missing
required_envs = {
    "DISCORD_TOKEN": TOKEN,
    "API_KEY": API_KEY,
    "API_URL": API_URL,
    "LOG_CHANNEL_ID": LOG_CHANNEL_ID,
    "ALLOWED_CHANNEL_ID": ALLOWED_CHANNEL_ID,
    "GUILD_ID": GUILD_ID,
}

for name, value in required_envs.items():
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")

# ==========================================================
# NON-SENSITIVE CONFIG
# ==========================================================
with open("config.yaml", "r") as f:
    cfg = yaml.safe_load(f)

SERVICES = cfg["services"]
ROLES = cfg["roles"]

# ==========================================================
# ROLE LIMITS
# ==========================================================
ROLE_LIMITS = {
    "free":   {"views": 100,  "likes": 10,  "shares": 10,  "follows": 0},
    "bronze": {"views": 3000, "likes": 200, "shares": 200, "follows": 0},
    "silver": {"views": 7000, "likes": 500, "shares": 500, "follows": 0},
}

# ==========================================================
# COOLDOWNS (SECONDS)
# ==========================================================
COOLDOWNS = {
    "jviews": 300,
    "jlikes": 300,
    "jshares": 3600,
    "jfollow": 86400,
}

user_cooldowns = {cmd: {} for cmd in COOLDOWNS}

# ==========================================================
# DISCORD SETUP
# ==========================================================
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ==========================================================
# HELPERS
# ==========================================================
def get_user_tier(member: discord.Member):
    role_names = [r.name for r in member.roles]

    if ROLES["silver"] in role_names:
        return "silver"
    if ROLES["bronze"] in role_names:
        return "bronze"
    if ROLES["free"] in role_names:
        return "free"
    return None


def place_order(service_id, link, quantity):
    payload = {
        "key": API_KEY,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity
    }
    r = requests.post(API_URL, data=payload, timeout=20)
    return r.json()


async def send_log(interaction, tier, service, quantity, link, order_id):
    channel = interaction.client.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="📦 JEET Order Logged",
        color=discord.Color.purple()
    )
    embed.add_field(name="User", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
    embed.add_field(name="Role", value=tier.capitalize(), inline=True)
    embed.add_field(name="Service", value=service.capitalize(), inline=True)
    embed.add_field(name="Quantity", value=str(quantity), inline=True)
    embed.add_field(name="Link", value=link, inline=False)
    embed.add_field(name="Order ID", value=str(order_id), inline=False)

    await channel.send(embed=embed)


def format_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")

    return " ".join(parts) if parts else "0s"

# ==========================================================
# CORE PROCESS
# ==========================================================
async def process(interaction: discord.Interaction, service_key: str, command_name: str):
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Use commands only in <#{ALLOWED_CHANNEL_ID}>",
            ephemeral=True
        )
        return

    tier = get_user_tier(interaction.user)
    if not tier:
        await interaction.response.send_message(
            "❌ You do not have access to JEET services.",
            ephemeral=True
        )
        return

    user_id = interaction.user.id
    now = time.time()

    last_used = user_cooldowns[command_name].get(user_id, 0)
    cooldown = COOLDOWNS[command_name]

    if now - last_used < cooldown:
        await interaction.response.send_message(
            f"⏳ Cooldown: {format_time(int(cooldown - (now - last_used)))}",
            ephemeral=True
        )
        return

    user_cooldowns[command_name][user_id] = now

    qty = ROLE_LIMITS[tier][service_key]
    if qty == 0:
        await interaction.response.send_message(
            "❌ This service is not available for your tier.",
            ephemeral=True
        )
        return

    service_id = SERVICES[service_key]
    link = interaction.data["options"][0]["value"]

    await interaction.response.send_message(
        f"⏳ **Placing Order...**\n"
        f"Service: `{service_key}`\n"
        f"Quantity: `{qty}`"
    )

    result = place_order(service_id, link, qty)

    if "order" in result:
        order_id = result["order"]
        await interaction.edit_original_response(
            content=(
                f"✅ **Order Placed**\n"
                f"👤 {interaction.user.mention}\n"
                f"📌 `{service_key}`\n"
                f"📦 `{qty}`\n"
                f"🆔 `{order_id}`"
            )
        )
        await send_log(interaction, tier, service_key, qty, link, order_id)
    else:
        await interaction.edit_original_response(
            content=f"❌ **Order Failed**\n```{result}```"
        )

# ==========================================================
# COMMANDS
# ==========================================================
@tree.command(name="jviews", description="Send TikTok views")
async def jviews(interaction: discord.Interaction, link: str):
    await process(interaction, "views", "jviews")


@tree.command(name="jlikes", description="Send TikTok likes")
async def jlikes(interaction: discord.Interaction, link: str):
    await process(interaction, "likes", "jlikes")


@tree.command(name="jshares", description="Send TikTok shares")
async def jshares(interaction: discord.Interaction, link: str):
    await process(interaction, "shares", "jshares")


@tree.command(name="jfollow", description="Send TikTok followers")
async def jfollow(interaction: discord.Interaction, link: str):
    await process(interaction, "follows", "jfollow")


@tree.command(name="jhelp", description="Shows JEET commands")
async def jhelp(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 JEET Commands", color=discord.Color.purple())
    embed.add_field(name="/jviews <link>", value="Send views", inline=False)
    embed.add_field(name="/jlikes <link>", value="Send likes", inline=False)
    embed.add_field(name="/jshares <link>", value="Send shares", inline=False)
    embed.add_field(name="/jfollow <link>", value="Send followers", inline=False)
    embed.add_field(name="/jstatus", value="Show cooldowns", inline=False)

    await interaction.response.send_message(embed=embed)


@tree.command(name="jstatus", description="Shows your cooldowns")
async def jstatus(interaction: discord.Interaction):
    now = time.time()
    lines = []

    for cmd in COOLDOWNS:
        last = user_cooldowns[cmd].get(interaction.user.id, 0)
        remaining = COOLDOWNS[cmd] - (now - last)
        lines.append(
            f"`{cmd}`: {format_time(int(remaining))}" if remaining > 0 else f"`{cmd}`: Ready"
        )

    embed = discord.Embed(
        title=f"⏱ {interaction.user.display_name} Cooldowns",
        description="\n".join(lines),
        color=discord.Color.purple()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================================
# READY
# ==========================================================
@client.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    print(f"✅ JEET Bot Online as {client.user}")

client.run(TOKEN)
