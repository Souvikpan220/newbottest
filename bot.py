import discord
from discord import app_commands
import requests
import yaml
import time
import os

# ---------- LOAD CONFIG ---------- #
with open("config.yaml", "r") as f:
    cfg = yaml.safe_load(f)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

LOG_CHANNEL_ID = cfg["discord"]["log_channel_id"]
ALLOWED_CHANNEL_ID = cfg["discord"]["allowed_channel_id"]
GUILD_ID = cfg["discord"]["guild_id"]

API_URL = cfg["api"]["url"]
API_KEY = os.getenv("API_KEY")

SERVICES = cfg["services"]
ROLES = cfg["roles"]

# ---------- ROLE LIMITS ---------- #
ROLE_LIMITS = {
    "free":   {"views": 100,  "likes": 10,  "shares": 10,  "follows": 0},
    "bronze": {"views": 3000, "likes": 200, "shares": 200, "follows": 0},
    "silver": {"views": 7000, "likes": 500, "shares": 500, "follows": 0},
}

# ---------- FREE ROLE COMMAND LIMIT ---------- #
FREE_COMMAND_LIMIT = 5
free_usage = {
    "jviews": {},
    "jlikes": {},
    "jshares": {},
    "jfollow": {}
}

# ---------- COOLDOWNS ---------- #
COOLDOWNS = {
    "jviews": 300,
    "jlikes": 300,
    "jshares": 3600,
    "jfollow": 86400
}
user_cooldowns = {cmd: {} for cmd in COOLDOWNS}

# ---------- DISCORD ---------- #
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---------- HELPERS ---------- #
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
        r = requests.post(API_URL, data=payload, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ReadTimeout:
        return {"error": "API timed out. Please try again later."}
    except requests.exceptions.RequestException as e:
        return {"error": f"API Error: {e}"}

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

# ---------- CORE ---------- #
async def process(interaction: discord.Interaction, service_key: str, command_name: str):
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Use commands in <#{ALLOWED_CHANNEL_ID}> only.",
            ephemeral=True
        )
        return

    tier = get_user_tier(interaction.user)
    if not tier:
        await interaction.response.send_message(
            "❌ You do not have access.",
            ephemeral=True
        )
        return

    user_id = interaction.user.id

    # ----- FREE ROLE LIMIT ----- #
    if tier == "free":
        used = free_usage[command_name].get(user_id, 0)
        if used >= FREE_COMMAND_LIMIT:
            await interaction.response.send_message(
                "❌ **Free tier limit reached.**\n"
                "Upgrade to **Bronze or Silver** to continue using this command.",
                ephemeral=True
            )
            return
        free_usage[command_name][user_id] = used + 1

    # ----- COOLDOWN ----- #
    now = time.time()
    last_used = user_cooldowns[command_name].get(user_id, 0)
    if now - last_used < COOLDOWNS[command_name]:
        await interaction.response.send_message(
            "⏳ Cooldown active. Please wait.",
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

    link = interaction.data["options"][0]["value"]
    service_id = SERVICES[service_key]

    await interaction.response.send_message(
        f"⏳ Placing order...\nService: `{service_key}`\nQuantity: `{qty}`"
    )

    result = place_order(service_id, link, qty)

    if "order" in result:
        await interaction.edit_original_response(
            content=(
                f"✅ **Order Placed**\n"
                f"Service: `{service_key}`\n"
                f"Quantity: `{qty}`\n"
                f"Order ID: `{result['order']}`"
            )
        )
        await send_log(interaction, tier, service_key, qty, link, result["order"])
    else:
        await interaction.edit_original_response(
            content=f"❌ **Order Failed**\n{result.get('error', 'Unknown error')}"
        )

# ---------- COMMANDS ---------- #
@tree.command(name="jviews")
async def jviews(interaction: discord.Interaction, link: str):
    await process(interaction, "views", "jviews")

@tree.command(name="jlikes")
async def jlikes(interaction: discord.Interaction, link: str):
    await process(interaction, "likes", "jlikes")

@tree.command(name="jshares")
async def jshares(interaction: discord.Interaction, link: str):
    await process(interaction, "shares", "jshares")

@tree.command(name="jfollow")
async def jfollow(interaction: discord.Interaction, link: str):
    await process(interaction, "follows", "jfollow")

# ---------- READY ---------- #
@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"JEET Bot Online as {client.user}")

client.run(TOKEN)
