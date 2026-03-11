"""
src/discord — Discord bot for realtime voice translation.

This package provides a Discord bot that integrates with the existing
RealtimeClient to deliver live voice-to-text translation in Discord voice channels.

Key components:
- bot.py: Discord bot with voice + text channel management.
- audio.py: DiscordAudioInput adapter implementing the AudioInput contract.
- main.py: CLI entry point.
"""

__all__ = ["DiscordAudioInput", "TranslationBot"]

from src.discord.audio import DiscordAudioInput
from src.discord.bot import TranslationBot
