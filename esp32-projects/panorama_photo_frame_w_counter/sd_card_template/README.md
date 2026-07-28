# sd_card_template

Template for the SD card's root layout. Copy these onto a FAT32-formatted card
(see `../../eink_sd_test/INSTALL.md`) and add your prepared photos.

```
/frame_config.xml            <- copy from here (edit <refresh_hours> / <counter>)
/pictures/                   <- create this; drop <name>.bin + <name>.xml pairs in
    <name>.bin, <name>.xml   <- produced by prepare_image.py (see ../README.md)
/counter_track.txt           <- created automatically by the frame; don't add it
```

`frame_config.xml` here uses the firmware's default of 2-hour cycling and a starting
`<counter>` of 0. The counter is the value shown top-left on the frame; the firmware
**rewrites `<counter>` in this file** each time a GPIO counter button is pressed, so it
persists there rather than in flash. Set it to whatever value you want the frame to
start counting from. The file is optional on the card — if absent or unparseable, the
frame falls back to 2 hours and counter 0.
