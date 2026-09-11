# Native desktop app

Install the dependency and launch from this directory:

```sh
python -m pip install -r requirements.txt
python native_app.py
```

The app uses Qt Multimedia for camera access, local motion detection, MP4/H.264 recording, playback, and a selectable save folder. The default is `Videos\Motion Camera`. Double-click a recording to play it, or right-click it to delete it.
