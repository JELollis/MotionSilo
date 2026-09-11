# Browser version

Run from a local development server because browsers commonly block camera access from `file://` URLs:

```sh
npx serve .
```

The browser version supports camera selection, live preview, motion-triggered WebM recording, playback, downloads, and—on browsers supporting the File System Access API—saving recordings to a user-selected folder. Browser security prevents it from silently selecting the system Videos library.
