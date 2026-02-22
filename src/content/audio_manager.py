import os

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
from PySide6.QtWidgets import QApplication

from src.content.config import AUDIO_DIR


class AudioManager(QObject):
    """Central audio manager for background music and short sound effects."""

    def __init__(self, audio_dir=AUDIO_DIR, music_volume=1.0, sfx_volume=1.0, parent=None):
        super().__init__(parent)
        self.audio_dir = audio_dir
        self._active_effects = []
        self._effect_aliases = {
            "dice_roll": "roll_1d10.wav",
            "combat_resolve": "combat_resolve.wav",
        }
        self._music_enabled = True
        self._sfx_enabled = True
        self._music_mode_requested = "stopped"  # "intro", "playlist", "stopped"
        self._sfx_volume = max(0.0, min(1.0, float(sfx_volume)))

        self._music_output = QAudioOutput(self)
        self._music_output.setVolume(max(0.0, min(1.0, music_volume)))

        self._music_player = QMediaPlayer(self)
        self._music_player.setAudioOutput(self._music_output)
        self._music_player.mediaStatusChanged.connect(self._on_music_media_status_changed)

        self._intro_track = self._find_intro_track()
        self._playlist_tracks = self._find_playlist_tracks()
        self._playlist_index = 0
        self._playlist_mode = False

    @staticmethod
    def from_app():
        app = QApplication.instance()
        if app is None:
            return None
        return getattr(app, "audio_manager", None)

    def play_intro_loop(self):
        self._music_mode_requested = "intro"
        if not self._music_enabled:
            return
        if not self._intro_track:
            print("AudioManager: intro.mp3 not found; intro music disabled.")
            return

        self._playlist_mode = False
        self._music_player.stop()
        self._music_player.setSource(QUrl.fromLocalFile(self._intro_track))
        self._music_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._music_player.play()

    def play_game_playlist(self):
        self._music_mode_requested = "playlist"
        if not self._music_enabled:
            return
        if not self._playlist_tracks:
            if self._intro_track:
                self.play_intro_loop()
            else:
                self.stop_music()
            return

        self._playlist_mode = True
        self._playlist_index = 0
        self._play_playlist_track(self._playlist_index)

    def stop_music(self):
        self._playlist_mode = False
        self._music_mode_requested = "stopped"
        self._music_player.stop()

    def set_music_volume(self, volume):
        self._music_output.setVolume(max(0.0, min(1.0, float(volume))))

    def set_music_volume_percent(self, value):
        self.set_music_volume(float(value) / 100.0)

    def get_music_volume_percent(self):
        return int(round(self._music_output.volume() * 100))

    def set_sfx_volume(self, volume):
        self._sfx_volume = max(0.0, min(1.0, float(volume)))

    def set_sfx_volume_percent(self, value):
        self.set_sfx_volume(float(value) / 100.0)

    def get_sfx_volume_percent(self):
        return int(round(self._sfx_volume * 100))

    def set_music_enabled(self, enabled):
        enabled = bool(enabled)
        if self._music_enabled == enabled:
            return
        self._music_enabled = enabled
        if not enabled:
            self._music_player.stop()
            return
        self._resume_requested_music_mode()

    def is_music_enabled(self):
        return self._music_enabled

    def set_sfx_enabled(self, enabled):
        enabled = bool(enabled)
        self._sfx_enabled = enabled
        if not enabled:
            for effect in list(self._active_effects):
                try:
                    effect.stop()
                except Exception:
                    pass

    def is_sfx_enabled(self):
        return self._sfx_enabled

    def register_effect_alias(self, alias, filename):
        self._effect_aliases[str(alias)] = str(filename)

    def play_effect_alias(self, alias, volume=1.0, loops=1, parent=None):
        filename = self._effect_aliases.get(alias)
        if not filename:
            print(f"AudioManager: unknown effect alias '{alias}'.")
            return None
        return self.play_effect_file(filename, volume=volume, loops=loops, parent=parent)

    def play_dice_roll(self, volume=1.0, parent=None):
        return self.play_effect_alias("dice_roll", volume=volume, loops=1, parent=parent)

    def play_combat_resolve(self, volume=1.0, parent=None):
        return self.play_effect_alias("combat_resolve", volume=volume, loops=1, parent=parent)

    def play_effect_file(self, filename, volume=1.0, loops=1, parent=None):
        if not self._sfx_enabled:
            return None
        path = self._resolve_audio_path(filename)
        if not path:
            print(f"AudioManager: effect not found '{filename}'.")
            return None

        effect = QSoundEffect(parent or self)
        effect.setSource(QUrl.fromLocalFile(path))
        effect_volume = max(0.0, min(1.0, float(volume)))
        effect.setVolume(effect_volume * self._sfx_volume)
        effect.setLoopCount(max(1, int(loops)))
        self._track_effect(effect)
        effect.play()
        return effect

    def _track_effect(self, effect):
        self._active_effects.append(effect)

        def _cleanup_if_done():
            if effect.isPlaying():
                return
            try:
                self._active_effects.remove(effect)
            except ValueError:
                pass

        effect.playingChanged.connect(_cleanup_if_done)

    def _play_playlist_track(self, index):
        if not self._playlist_tracks:
            return
        index = index % len(self._playlist_tracks)
        self._playlist_index = index
        self._music_player.stop()
        self._music_player.setSource(QUrl.fromLocalFile(self._playlist_tracks[index]))
        self._music_player.setLoops(1)
        self._music_player.play()

    def _on_music_media_status_changed(self, status):
        if not self._playlist_mode:
            return
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        self._play_playlist_track(self._playlist_index + 1)

    def _find_intro_track(self):
        if not os.path.isdir(self.audio_dir):
            return None
        for name in os.listdir(self.audio_dir):
            if name.lower() == "intro.mp3":
                return os.path.join(self.audio_dir, name)
        return None

    def _find_playlist_tracks(self):
        if not os.path.isdir(self.audio_dir):
            return []
        tracks = []
        for name in sorted(os.listdir(self.audio_dir), key=str.lower):
            if not name.lower().endswith(".mp3"):
                continue
            if name.lower() == "intro.mp3":
                continue
            tracks.append(os.path.join(self.audio_dir, name))
        return tracks

    def _resolve_audio_path(self, filename):
        if not filename:
            return None
        if os.path.isabs(filename) and os.path.exists(filename):
            return filename
        candidate = os.path.join(self.audio_dir, filename)
        if os.path.exists(candidate):
            return candidate
        return None

    def _resume_requested_music_mode(self):
        if self._music_mode_requested == "intro":
            self.play_intro_loop()
        elif self._music_mode_requested == "playlist":
            self.play_game_playlist()
