# sd_card_template

Template for the SD card's root layout. Copy these onto a FAT32-formatted card
(see `../../eink_sd_test/INSTALL.md`) and add your prepared photos.

```
/frame_config.xml            <- copy from here (edit refresh_hours / counter / timezone)
/pictures/                   <- drop <name>.bin + <name>.xml pairs in
    <name>.bin, <name>.xml   <- produced by prepare_image.py (see ../README.md)
/counter_track.txt           <- created automatically by the frame; don't add it
```

Unlike the deep-sleep version of this frame, **`/pictures/` is created for you**
if it's missing — the firmware calls `SD.mkdir()` at mount. You can also skip
the card shuffle entirely and add photos over the web UI's Upload page.

`frame_config.xml` is optional. Without it (or with unparseable values) the
frame falls back to a 2-hour interval, counter 0, and US Central time. The
firmware **rewrites values in this file in place**, preserving the comments
around them: `<counter>` on every counter change, `<timezone>` when you save a
new one from the web UI's Clock page.

Note the frame keeps this card mounted continuously — use the web UI's **Eject
card** button before pulling it. See `../README.md`.
