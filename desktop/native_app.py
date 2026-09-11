"""MotionSilo - native Windows desktop app.

Uses Qt Multimedia for camera access, preview, motion sampling, and recording.
Clips are written to the user's Videos/MotionSilo folder by default.
"""

from __future__ import annotations

import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaFormat,
    QMediaPlayer,
    QMediaRecorder,
    QVideoFrame,
    QVideoSink,
)
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QDialog,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)


APP_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = APP_DIR / "recordings"
PREBUFFER_SECONDS = 10


class MotionSilo(QMainWindow):
    motion = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MotionSilo")
        self.setWindowIcon(QIcon(str(APP_DIR / "app_icon.svg")))
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)

        self.camera: QCamera | None = None
        self.stream = QMediaCaptureSession()
        self.recorder = QMediaRecorder()
        # QVideoWidget owns the sink that receives its frames. Reusing that
        # sink lets motion analysis observe frames without replacing the
        # visible preview output on the capture session.
        self.sink: QVideoSink | None = None
        self.monitoring = False
        self.previous_frame: bytes | None = None
        self.previous_mean: float | None = None
        self.motion_hits = 0
        self.frames_seen = 0
        self.recording_started: datetime | None = None
        self.recording_path: Path | None = None
        self.buffer_dir = Path(tempfile.gettempdir()) / "MotionSilo" / "prebuffer"
        self.buffer_segments: list[Path] = []
        self.motion_event_active = False
        self.capture_current_segment = False
        self.event_started: datetime | None = None
        self.event_part = 0
        self.rotating_buffer = False
        self.settings = QSettings("MotionSilo", "MotionSilo")
        default_folder = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)
        default_folder = Path(default_folder) / "MotionSilo" if default_folder else APP_DIR / "recordings"
        saved_folder = self.settings.value("save_folder", "")
        self.save_folder = Path(saved_folder) if saved_folder else default_folder
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.setSingleShot(True)
        self.cooldown_timer.timeout.connect(self.finish_motion_event)
        self.buffer_timer = QTimer(self)
        self.buffer_timer.timeout.connect(self.rotate_buffer_segment)
        self.motion_timer = QTimer(self)
        self.motion_timer.timeout.connect(self.sample_motion)
        self.motion_clear_timer = QTimer(self)
        self.motion_clear_timer.setSingleShot(True)
        self.motion_clear_timer.timeout.connect(self.clear_motion_indicator)

        self.build_ui()
        self.stream.setVideoOutput(self.video)
        self.stream.setRecorder(self.recorder)
        self.sink = self.video.videoSink()
        self.sink.videoFrameChanged.connect(self.on_frame)
        self.recorder.recorderStateChanged.connect(self.recorder_state_changed)
        self.recorder.errorOccurred.connect(self.recorder_error)
        self.recorder.actualLocationChanged.connect(self.actual_location_changed)
        self.refresh_cameras()

    def build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget { background: #101312; color: #e8ebe5; font-family: Segoe UI; font-size: 13px; }
            QMainWindow { background: #101312; }
            QGroupBox { border: 1px solid #2d3531; border-radius: 5px; margin-top: 12px; padding: 20px 16px 16px; background: #171c1a; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 6px; color: #d5f28a; font-size: 11px; font-weight: 700; }
            QComboBox, QSpinBox { background: #202924; border: 1px solid #3a4640; border-radius: 3px; padding: 9px; color: #e8ebe5; }
            QPushButton { border-radius: 3px; padding: 10px; font-weight: 600; }
            QPushButton#primary { background: #d5f28a; color: #182014; }
            QPushButton#primary:disabled, QPushButton:disabled { color: #65716a; background: #202622; }
            QPushButton#stop { background: transparent; color: #a4aea7; border: 1px solid #2d3531; }
            QPushButton#stop:enabled { background: #f6a36e; color: #25140c; border-color: #f6a36e; }
            QPushButton#stop:enabled:hover { background: #ffc08e; border-color: #ffc08e; }
            QSlider::groove:horizontal { height: 3px; background: #2d3531; }
            QSlider::handle:horizontal { background: #d5f28a; width: 14px; margin: -5px 0; border-radius: 7px; }
            QLabel#muted { color: #8c9690; }
            QLabel#status { color: #d5f28a; font-weight: 700; }
            QListWidget { border: 1px solid #2d3531; background: #171c1a; }
            QStatusBar { color: #8c9690; border-top: 1px solid #2d3531; }
            QLabel#motionStatus { color: #8c9690; font-size: 12px; }
            QLabel#motionStatus[detected="true"] { color: #f6a36e; font-weight: 700; }
            QProgressBar { border: 0; background: #28302c; height: 4px; }
            QProgressBar::chunk { background: #d5f28a; }
        """)
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(30, 26, 30, 20); root.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel("◉  motion<span style='color:#d5f28a;font-weight:400'>silo</span>"); title.setTextFormat(Qt.RichText); title.setStyleSheet("font-size: 21px; font-weight: 800")
        self.connection = QLabel("●  Camera not connected"); self.connection.setObjectName("muted")
        header.addWidget(title); header.addStretch(); header.addWidget(self.connection); root.addLayout(header)

        body = QGridLayout(); body.setColumnStretch(0, 1); body.setColumnStretch(1, 0); body.setColumnMinimumWidth(1, 320); body.setSpacing(16); root.addLayout(body, 1)
        preview_box = QGroupBox("LIVE PREVIEW")
        preview_layout = QVBoxLayout(preview_box); preview_layout.setContentsMargins(0, 8, 0, 0)
        self.video = QVideoWidget(); self.video.setMinimumSize(0, 0); self.video.setAspectRatioMode(Qt.KeepAspectRatio); preview_layout.addWidget(self.video, 1)
        self.activity = QLabel("Waiting for camera"); self.activity.setObjectName("muted"); self.activity.setMinimumHeight(20); preview_layout.addWidget(self.activity)
        motion_row = QHBoxLayout(); self.motion_status = QLabel("●  No motion detected"); self.motion_status.setObjectName("motionStatus"); self.motion_status.setMinimumHeight(24); motion_row.addWidget(self.motion_status)
        motion_row.addStretch(); motion_row.addWidget(QLabel("Activity")); self.activity_meter = QProgressBar(); self.activity_meter.setRange(0, 100); self.activity_meter.setValue(0); self.activity_meter.setTextVisible(False); self.activity_meter.setFixedWidth(130); motion_row.addWidget(self.activity_meter); preview_layout.addLayout(motion_row)
        body.addWidget(preview_box, 0, 0, 2, 1)

        camera_box = QGroupBox("CAMERA SOURCE"); camera_form = QFormLayout(camera_box); camera_form.setVerticalSpacing(12)
        self.camera_select = QComboBox(); camera_form.addRow("Available cameras", self.camera_select)
        refresh = QPushButton("↻  Refresh camera list"); refresh.clicked.connect(self.refresh_cameras); camera_form.addRow(refresh)
        self.camera_hint = QLabel("Allow camera access to discover devices."); self.camera_hint.setObjectName("muted"); self.camera_hint.setWordWrap(True); camera_form.addRow(self.camera_hint)
        self.camera_select.currentIndexChanged.connect(self.select_camera); body.addWidget(camera_box, 0, 1)

        settings = QGroupBox("DETECTION SETTINGS"); form = QFormLayout(settings); form.setVerticalSpacing(15)
        self.sensitivity = QSlider(Qt.Horizontal); self.sensitivity.setRange(1, 3); self.sensitivity.setValue(2); form.addRow("Sensitivity", self.sensitivity)
        self.sensitivity_label = QLabel("Medium"); self.sensitivity_label.setObjectName("muted"); form.addRow("", self.sensitivity_label)
        self.cooldown = QSpinBox(); self.cooldown.setRange(0, 60); self.cooldown.setValue(10); self.cooldown.setSuffix(" sec"); form.addRow("Keep recording", self.cooldown)
        self.sensitivity.valueChanged.connect(lambda v: self.sensitivity_label.setText(["Low", "Medium", "High"][v - 1])); body.addWidget(settings, 1, 1)

        actions = QHBoxLayout(); self.start = QPushButton("▶  Start monitoring"); self.start.setObjectName("primary"); self.start.setEnabled(False); self.start.clicked.connect(self.start_monitoring); actions.addWidget(self.start)
        self.stop = QPushButton("■  Stop monitoring"); self.stop.setObjectName("stop"); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_monitoring); actions.addWidget(self.stop); root.addLayout(actions)

        recordings_box = QGroupBox("RECORDINGS")
        recordings_layout = QVBoxLayout(recordings_box)
        save_row = QHBoxLayout()
        save_label = QLabel("Save location"); save_label.setObjectName("muted")
        self.save_location = QLabel(); self.save_location.setToolTip(str(self.save_folder)); self.save_location.setTextInteractionFlags(Qt.TextSelectableByMouse); self.save_location.setStyleSheet("color:#e8ebe5")
        choose_folder = QPushButton("Choose folder…"); choose_folder.clicked.connect(self.choose_save_folder)
        save_row.addWidget(save_label); save_row.addWidget(self.save_location, 1); save_row.addWidget(choose_folder); recordings_layout.addLayout(save_row)
        self.recordings = QListWidget(); self.recordings.setMinimumHeight(105); self.recordings.setContextMenuPolicy(Qt.CustomContextMenu); self.recordings.customContextMenuRequested.connect(self.show_recording_menu); recordings_layout.addWidget(self.recordings); root.addWidget(recordings_box)
        self.recordings.itemDoubleClicked.connect(self.play_selected_recording)
        self.setStatusBar(QStatusBar()); self.statusBar().showMessage(f"Recordings folder: {self.save_folder}")
        self.update_save_location_label()
        self.load_recordings()

    def refresh_cameras(self) -> None:
        self.camera_select.blockSignals(True); self.camera_select.clear()
        cameras = QMediaDevices.videoInputs()
        for index, device in enumerate(cameras): self.camera_select.addItem(device.description() or f"Camera {index + 1}", device)
        self.camera_select.blockSignals(False)
        self.camera_hint.setText(f"{len(cameras)} camera(s) available." if cameras else "No video input was found.")
        if cameras: self.select_camera(0)

    def update_save_location_label(self) -> None:
        self.save_location.setText(str(self.save_folder))
        self.save_location.setToolTip(str(self.save_folder))
        self.statusBar().showMessage(f"Recordings folder: {self.save_folder}")

    def choose_save_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose recording folder", str(self.save_folder))
        if selected:
            self.save_folder = Path(selected)
            self.settings.setValue("save_folder", str(self.save_folder))
            self.update_save_location_label()
            self.load_recordings()

    def load_recordings(self) -> None:
        self.recordings.clear()
        if not self.save_folder.exists(): return
        for path in sorted(self.save_folder.glob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True):
            self.add_recording(path)

    def play_selected_recording(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path: PlaybackDialog(Path(path), self).exec()

    def show_recording_menu(self, position) -> None:
        item = self.recordings.itemAt(position)
        if item is None: return
        menu = QMenu(self)
        play_action = menu.addAction("▶  Play recording")
        delete_action = menu.addAction("Delete recording")
        chosen = menu.exec(self.recordings.viewport().mapToGlobal(position))
        if chosen == play_action: self.play_selected_recording(item)
        elif chosen == delete_action: self.delete_recording(item)

    def delete_recording(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.UserRole))
        try:
            is_local = path.resolve().parent == self.save_folder.resolve()
        except OSError:
            is_local = False
        if not is_local: self.statusBar().showMessage("That recording is outside the selected save folder."); return
        answer = QMessageBox.question(self, "Delete recording?", f"Delete {path.name} permanently?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes: return
        try:
            path.unlink()
            self.recordings.takeItem(self.recordings.row(item))
            self.statusBar().showMessage(f"Deleted recording: {path.name}")
        except OSError as error:
            QMessageBox.warning(self, "Could not delete recording", str(error))

    def select_camera(self, index: int) -> None:
        if self.monitoring or index < 0: return
        device = self.camera_select.itemData(index)
        if device is None: return
        if self.camera: self.camera.stop()
        self.camera = QCamera(device); self.stream.setCamera(self.camera); self.camera.start()
        self.start.setEnabled(True); self.connection.setText("●  Camera connected"); self.connection.setStyleSheet("color:#d5f28a"); self.activity.setText("Live preview ready")

    def on_frame(self, frame: QVideoFrame) -> None:
        if self.monitoring and frame.isValid():
            self.current_frame = frame.toImage()
            self.frames_seen += 1

    def sample_motion(self) -> None:
        image = getattr(self, "current_frame", None)
        if image is None or image.isNull(): return
        # Smooth downsampling reduces sensor noise; brightness normalization
        # suppresses whole-frame exposure changes common in dark scenes.
        image = image.convertToFormat(QImage.Format_Grayscale8).scaled(80, 45, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        frame_width, frame_height = image.width(), image.height()
        raw = bytes(image.constBits())
        stride = image.bytesPerLine()
        current = b"".join(raw[row * stride: row * stride + frame_width] for row in range(frame_height))
        if len(current) != frame_width * frame_height: return
        current_mean = sum(current) / max(1, len(current))
        if self.previous_frame is None or len(self.previous_frame) != len(current):
            self.previous_frame = current
            self.previous_mean = current_mean
            return
        # Compare downsampled grayscale frames. The high setting uses a lower
        # pixel delta and area threshold so slow movement in a dark porch
        # scene, such as a cat approaching a trap, is not missed.
        pixel_delta = {1: 24, 2: 18, 3: 12}[self.sensitivity.value()]
        area_threshold = {1: 0.045, 2: 0.020, 3: 0.008}[self.sensitivity.value()]
        previous_mean = self.previous_mean or current_mean
        # Score 4x4 regions instead of individual pixels. Isolated sensor
        # noise can affect many pixels, but a moving subject changes adjacent
        # pixels within the same regions.
        width, height, block = frame_width, frame_height, 4
        changed_blocks = 0
        total_blocks = ((width + block - 1) // block) * ((height + block - 1) // block)
        for block_y in range(0, height, block):
            for block_x in range(0, width, block):
                changed = 0
                for y in range(block_y, min(block_y + block, height)):
                    offset = y * width
                    for x in range(block_x, min(block_x + block, width)):
                        if abs((current[offset + x] - current_mean) - (self.previous_frame[offset + x] - previous_mean)) >= pixel_delta:
                            changed += 1
                if changed >= 2: changed_blocks += 1
        change_ratio = changed_blocks / max(1, total_blocks)
        self.previous_frame = current
        self.previous_mean = current_mean
        self.activity_meter.setValue(min(100, round(change_ratio * 1200)))
        if change_ratio >= area_threshold:
            self.motion_hits += 1
        else:
            self.motion_hits = max(0, self.motion_hits - 1)
        if self.motion_hits >= 2:
            self.motion_hits = 0
            self.motion_detected()

    def motion_detected(self) -> None:
        self.motion_status.setText("●  Motion detected — recording")
        self.motion_status.setProperty("detected", True); self.motion_status.style().unpolish(self.motion_status); self.motion_status.style().polish(self.motion_status)
        self.activity.setText("Motion detected — recording")
        self.motion_clear_timer.start(1200)
        if not self.motion_event_active:
            self.motion_event_active = True
            self.capture_current_segment = True
            self.event_started = datetime.now()
            self.event_part = 0
            self.preserve_buffer_segments()
        self.cooldown_timer.start(self.cooldown.value() * 1000 + 1000)

    def clear_motion_indicator(self) -> None:
        if self.monitoring and self.recorder.recorderState() != QMediaRecorder.RecordingState:
            self.motion_status.setText("●  No motion detected")
            self.motion_status.setProperty("detected", False); self.motion_status.style().unpolish(self.motion_status); self.motion_status.style().polish(self.motion_status)

    def start_buffer_segment(self) -> None:
        if self.recorder.recorderState() != QMediaRecorder.StoppedState: return
        try:
            self.buffer_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.statusBar().showMessage(f"Cannot create temporary recording folder: {error}")
            return
        self.recording_started = datetime.now()
        self.recording_path = self.buffer_dir / f"segment_{self.recording_started:%Y%m%d_%H%M%S_%f}.mp4"
        media_format = QMediaFormat()
        media_format.setFileFormat(QMediaFormat.MPEG4)
        media_format.setVideoCodec(QMediaFormat.H264)
        self.recorder.setMediaFormat(media_format)
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self.recording_path)))
        self.recorder.record()

    def clear_buffer_segments(self) -> None:
        for path in self.buffer_segments:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        self.buffer_segments.clear()

    def rotate_buffer_segment(self) -> None:
        if self.recorder.recorderState() == QMediaRecorder.RecordingState and not self.rotating_buffer:
            self.rotating_buffer = True
            self.recorder.stop()

    def preserve_buffer_segments(self) -> None:
        for path in list(self.buffer_segments):
            self.save_buffer_segment(path, prebuffer=True)
        self.buffer_segments.clear()

    def save_buffer_segment(self, path: Path, prebuffer: bool = False) -> None:
        if not path.exists(): return
        try:
            self.save_folder.mkdir(parents=True, exist_ok=True)
            started = self.event_started or datetime.now()
            suffix = "pre" if prebuffer else f"part{self.event_part:02d}"
            destination = self.save_folder / f"motion_{started:%Y%m%d_%H%M%S}_{suffix}.mp4"
            shutil.move(str(path), str(destination))
            if not prebuffer: self.event_part += 1
            self.add_recording(destination)
        except OSError as error:
            self.statusBar().showMessage(f"Could not save recording segment: {error}")

    def finish_motion_event(self) -> None:
        if self.motion_event_active:
            self.motion_event_active = False
            self.capture_current_segment = True

    def actual_location_changed(self, location: QUrl) -> None:
        if location.isValid() and location.toLocalFile():
            self.recording_path = Path(location.toLocalFile())

    def stop_recording(self) -> None:
        if self.recorder.recorderState() == QMediaRecorder.RecordingState: self.recorder.stop()

    def recorder_state_changed(self, state: QMediaRecorder.RecorderState) -> None:
        if state == QMediaRecorder.RecordingState:
            self.motion_status.setText("●  Recording — motion detected" if self.motion_event_active else "●  Monitoring — pre-buffer active")
            self.motion_status.setProperty("detected", self.motion_event_active); self.motion_status.style().unpolish(self.motion_status); self.motion_status.style().polish(self.motion_status)
            self.statusBar().showMessage("Recording motion event" if self.motion_event_active else f"Pre-buffer active ({PREBUFFER_SECONDS}s)")
        elif state == QMediaRecorder.StoppedState and self.recording_path:
            finished = self.recording_path
            self.recording_path = None
            self.rotating_buffer = False
            if self.motion_event_active or self.capture_current_segment:
                self.save_buffer_segment(finished)
                self.capture_current_segment = False
            elif self.monitoring:
                self.buffer_segments.append(finished)
                while len(self.buffer_segments) > 1:
                    stale = self.buffer_segments.pop(0)
                    try: stale.unlink(missing_ok=True)
                    except OSError: pass
            else:
                try: finished.unlink(missing_ok=True)
                except OSError: pass
            if self.monitoring:
                self.start_buffer_segment()
            else:
                self.motion_status.setText("●  No motion detected")
                self.motion_status.setProperty("detected", False); self.motion_status.style().unpolish(self.motion_status); self.motion_status.style().polish(self.motion_status)

    def add_recording(self, path: Path) -> None:
        if not path.exists(): return
        item = QListWidgetItem(f"▶  {path.name}     {path.stat().st_size / 1024:.0f} KB"); item.setData(Qt.UserRole, str(path)); item.setToolTip(f"Double-click to play\n{path}"); self.recordings.addItem(item)
        self.statusBar().showMessage(f"Saved recording to {path}")

    def recorder_error(self, error: QMediaRecorder.Error, message: str) -> None:
        if message:
            self.activity.setText(f"Recording error: {message}")
            self.statusBar().showMessage(f"Recorder error: {message}")

    def start_monitoring(self) -> None:
        self.clear_buffer_segments(); self.monitoring = True; self.previous_frame = None; self.previous_mean = None; self.motion_hits = 0; self.frames_seen = 0; self.start.setEnabled(False); self.stop.setEnabled(True); self.camera_select.setEnabled(False); self.motion_status.setText("●  Monitoring — no motion detected"); self.motion_status.setProperty("detected", False); self.motion_status.style().unpolish(self.motion_status); self.motion_status.style().polish(self.motion_status); self.activity.setText("Monitoring for movement…"); self.statusBar().showMessage(f"Monitoring active — {PREBUFFER_SECONDS}s pre-buffer enabled"); self.start_buffer_segment(); self.buffer_timer.start(PREBUFFER_SECONDS * 1000); self.motion_timer.start(250)

    def stop_monitoring(self) -> None:
        self.monitoring = False; self.motion_timer.stop(); self.buffer_timer.stop(); self.cooldown_timer.stop(); self.stop_recording(); self.clear_buffer_segments(); self.start.setEnabled(True); self.stop.setEnabled(False); self.camera_select.setEnabled(True); self.activity.setText("Monitoring stopped")

    def closeEvent(self, event) -> None:
        self.stop_monitoring()
        if self.camera: self.camera.stop()
        event.accept()

class PlaybackDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Playback — {path.name}")
        self.resize(900, 590)
        self.setStyleSheet("""
            QDialog { background: #101312; color: #e8ebe5; }
            QSlider::groove:horizontal { height: 4px; background: #2d3531; }
            QSlider::handle:horizontal { background: #d5f28a; width: 14px; margin: -5px 0; border-radius: 7px; }
            QPushButton { background: #d5f28a; color: #182014; border: 0; border-radius: 3px; padding: 9px 18px; font-weight: 600; }
            QLabel { color: #8c9690; }
        """)
        layout = QVBoxLayout(self); layout.setContentsMargins(20, 20, 20, 16); layout.setSpacing(12)
        self.video = QVideoWidget(); layout.addWidget(self.video, 1)
        self.player = QMediaPlayer(self); self.player.setVideoOutput(self.video); self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 0); self.slider.sliderMoved.connect(self.player.setPosition); layout.addWidget(self.slider)
        controls = QHBoxLayout(); self.play = QPushButton("▶  Play"); self.play.clicked.connect(self.toggle_play); controls.addWidget(self.play)
        self.time = QLabel("00:00 / 00:00"); controls.addWidget(self.time); controls.addStretch(); close = QPushButton("Close"); close.clicked.connect(self.close); controls.addWidget(close); layout.addLayout(controls)
        self.player.durationChanged.connect(self.duration_changed); self.player.positionChanged.connect(self.position_changed); self.player.playbackStateChanged.connect(self.playback_state_changed); self.player.mediaStatusChanged.connect(lambda status: self.player.play() if status == QMediaPlayer.MediaStatus.LoadedMedia else None)

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState: self.player.pause()
        else: self.player.play()

    def duration_changed(self, duration: int) -> None:
        self.slider.setRange(0, duration); self.update_time(self.player.position(), duration)

    def position_changed(self, position: int) -> None:
        self.slider.setValue(position); self.update_time(position, self.player.duration())

    def update_time(self, position: int, duration: int) -> None:
        def fmt(value: int) -> str:
            seconds = max(0, value // 1000); return f"{seconds // 60:02d}:{seconds % 60:02d}"
        self.time.setText(f"{fmt(position)} / {fmt(duration)}")

    def playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play.setText("Ⅱ  Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "▶  Play")

    def closeEvent(self, event) -> None:
        self.player.stop(); event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv); app.setWindowIcon(QIcon(str(APP_DIR / "app_icon.svg"))); window = MotionSilo(); window.show(); sys.exit(app.exec())
