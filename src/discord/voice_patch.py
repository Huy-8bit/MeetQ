"""
Monkeypatch discord-ext-voice-recv to handle OpusError gracefully.

Without this patch, OpusError in PacketRouter crashes the router thread
and stops all audio reception.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord.opus import OpusError

if TYPE_CHECKING:
    from discord.ext.voice_recv.router import PacketRouter

logger = logging.getLogger(__name__)


def patched_do_run(self: "PacketRouter") -> None:
    """
    Patched _do_run that continues on OpusError instead of crashing.
    
    Original implementation in discord-ext-voice-recv/router.py crashes
    the entire router thread when Opus decoder encounters corrupted packets.
    
    This is common when joining voice channels mid-stream or with network issues.
    """
    while not self._end_thread.is_set():
        self.waiter.wait()
        with self._lock:
            for decoder in self.waiter.items:
                try:
                    data = decoder.pop_data()
                    if data is not None:
                        self.sink.write(data.source, data)
                except OpusError as e:
                    # Opus decoder error - common with corrupted/incomplete packets
                    # Log once and continue instead of crashing
                    if not hasattr(self, '_opus_error_logged'):
                        logger.warning(
                            f"OpusError in decoder (SSRC {decoder.ssrc}): {e}. "
                            "This is normal when joining mid-stream. Continuing..."
                        )
                        self._opus_error_logged = True
                    continue
                except Exception as e:
                    # Other exceptions should still be logged
                    logger.error(f"Unexpected error in decoder: {e}", exc_info=True)
                    continue


def apply_voice_recv_patch() -> None:
    """
    Apply monkeypatch to discord-ext-voice-recv PacketRouter.
    
    Call this before starting the bot to enable resilient audio reception.
    """
    try:
        from discord.ext.voice_recv.router import PacketRouter
        
        # Store original method for potential rollback
        if not hasattr(PacketRouter, '_original_do_run'):
            PacketRouter._original_do_run = PacketRouter._do_run
        
        # Apply patch
        PacketRouter._do_run = patched_do_run
        
        logger.info("✅ Applied discord-ext-voice-recv OpusError patch")
        
    except ImportError:
        logger.warning("discord-ext-voice-recv not installed - patch not applied")
    except Exception as e:
        logger.error(f"Failed to apply voice_recv patch: {e}")
