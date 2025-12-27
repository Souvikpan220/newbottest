import os
import time
import yaml
import requests
import discord
from discord import app_commands
from requests.exceptions import RequestException, Timeout

# ==========================================================
# ENVIRONMENT VARIABLES (RAILWAY SECRETS)
# ==========================================================
TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_KEY")
API_URL = os.getenv("API_URL")

LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))

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
# FREE ROLE USAGE LIMIT
# ==========================================================
FREE_COMMAND_LIMIT = 5
free_usage = {}  # {user_id: {command: count}}

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

    try:
        r = requests.post(API_URL, data=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    except Timeout:
        return {"error": "⏳ API timeout. Please try again later."}

    except RequestException as e:
        return {"error": f"❌ API error: {str(e)}"}


async def send_log(interaction, tier, service, quantity, link, order_id):
    channel = interaction.client.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(title="📦 JEET Order Logged", color=discord.Color.purple())
    embed.add_field(name="User", value=f"{interaction.user} ({interaction.user.id})", inline=False)
    embed.add_field(name="Tier", value=tier.capitalize(), inline=True)
    embed.add_field(name="Service", value=service, inline=True)
    embed.add_field(name="Quantity", value=quantity, inline=True)
    embed.add_field(name="Link", value=link, inline=False)
    embed.add_field(name="Order ID", value=order_id, inline=False)

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
            f"❌ Commands only allowed in <#{ALLOWED_CHANNEL_ID}>",
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

    # ---------------- FREE ROLE USAGE CHECK ----------------
    if tier == "free":
        free_usage.setdefault(user_id, {})
        used = free_usage[user_id].get(command_name, 0)

        if used >= FREE_COMMAND_LIMIT:
            await interaction.response.send_message(
                "🚫 **Free limit reached**\n"
                "You have used this command 5 times.\n"
                "**Buy Premium to unlock unlimited usage.** 💎",
                ephemeral=True
            )
            return

    # ---------------- COOLDOWN CHECK ----------------
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
        f"⏳ **Placing Order...**\nService: `{service_key}`\nQuantity: `{qty}`"
    )

    result = place_order(service_id, link, qty)

    if "error" in result:
        await interaction.edit_original_response(content=result["error"])
        return

    if "order" in result:
        order_id = result["order"]

        # Increase FREE usage count only on success
        if tier == "free":
            free_usage[user_id][command_name] = free_usage[user_id].get(command_name, 0) + 1

        await interaction.edit_original_response(
            content=(
                f"✅ **Order Placed Successfully**\n"
                f"👤 {interaction.user.mention}\n"
                f"📌 `{service_key}`\n"
                f"📦 `{qty}`\n"
                f"🆔 `{order_id}`"
            )
        )

        await send_log(interaction, tier, service_key, qty, link, order_id)

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

# ==========================================================
# READY
# ==========================================================
@client.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    print(f"✅ JEET Bot Online as {client.user}")

client.run(TOKEN)
