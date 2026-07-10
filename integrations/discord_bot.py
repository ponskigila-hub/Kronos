"""
Discord adapter (item #9). Requires: pip install discord.py
Set DISCORD_BOT_TOKEN in your .env (see .env.example).

Usage:
    python integrations/discord_bot.py

Commands work exactly like the CLI, e.g.:
    forecast aapl
    compare tsla nvda
    why is bitcoin falling
    add nvda to my watchlist
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord

from assistant.config import DISCORD_BOT_TOKEN
from assistant.core_assistant import StockAssistant

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
bot = StockAssistant()


@client.event
async def on_ready():
    print(f"Logged in as {client.user} -- Kronos assistant is online.")


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if client.user not in message.mentions and not isinstance(message.channel, discord.DMChannel):
        return  # only respond to DMs or when @mentioned in a server

    text = message.content
    if client.user in message.mentions:
        text = text.replace(f"<@{client.user.id}>", "").strip()

    async with message.channel.typing():
        # Discord users are identified per-channel-or-DM so watchlists/context
        # are personal to each person, not shared across the server.
        user_id = f"discord-{message.author.id}"
        result = bot.handle_message(user_id, text)

        await message.channel.send(result["text"][:1900])  # Discord message length limit

        if result.get("image_path"):
            # Preferred path: the matplotlib PNG generated alongside the
            # forecast (assistant.charts.build_forecast_png), same style as
            # the original scripts -- no extra dependency needed.
            await message.channel.send(file=discord.File(result["image_path"]))
        elif result.get("chart") is not None:
            path = f"/tmp/kronos_chart_{message.author.id}.png"
            try:
                result["chart"].write_image(path)  # requires `kaleido`
                await message.channel.send(file=discord.File(path))
            except Exception:
                # kaleido not installed / image export failed -- fall back to
                # sending an interactive HTML file instead.
                html_path = f"/tmp/kronos_chart_{message.author.id}.html"
                result["chart"].write_html(html_path)
                await message.channel.send(file=discord.File(html_path))


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("Set DISCORD_BOT_TOKEN in your .env file before running this bot.")
    client.run(DISCORD_BOT_TOKEN)
