# Open-Source Film Simulation Capable RPi Camera

Open source Raspberry Pi camera script with film simulation, tap-to-zoom, focus peaking, manual shutter control, and on-screen exposure tuning.

Built in compact Raspberry Pi Zero W and higher-performance Raspberry Pi 5 configurations with the HQ Camera attachment. This project was inspired by the camera builds and film simulation ideas shared by [Camera Hacks by Malcolm Jay](https://substack.com/@camerahacksbymalcolmjay), [this](https://substack.com/home/post/p-171702270?source=queue) one in particular.

## Camera Builds

### Raspberry Pi Zero W

For a new compact build, a Raspberry Pi Zero 2 W is recommended. Due to price surges, the only board I could find for this build was an original Raspberry Pi Zero W, which is what the photos and experimental script configuration show.

<img src="images/builds/pi-zero-camera-front.jpeg" alt="Front of the Raspberry Pi Zero W film simulation camera" width="480">

_The compact experimental Pi Zero W build with its camera module, touchscreen, shutter button, and UPS-Lite base._

<img src="images/builds/pi-zero-camera-controls.jpeg" alt="Touchscreen controls on the Raspberry Pi Zero W film simulation camera" width="480">

_The Pi Zero W rear touchscreen showing the live preview, film profile, exposure controls, and 12 MP photo mode._

### Raspberry Pi 5

<img src="images/builds/pi-5-camera-front.jpeg" alt="Front of the Raspberry Pi 5 film simulation camera" width="480">

_The Raspberry Pi 5 build with its HQ Camera, 6 mm lens, physical shutter button, and power bank base._

<img src="images/builds/pi-5-camera-controls.jpeg" alt="Touchscreen controls on the Raspberry Pi 5 film simulation camera" width="480">

_The rear 3.5-inch touchscreen showing the live preview and exposure controls._

<img src="images/builds/pi-5-camera-in-use.jpeg" alt="Raspberry Pi 5 film simulation camera in use" width="480">

_The handheld Raspberry Pi 5 build framing a shot through the live preview._

## Sample Photos

<img src="images/samples/classic-chrome.png" alt="Classic Chrome sample photo of the San Francisco skyline" width="480">

_Classic Chrome — ISO 100, 1/814 s._

<img src="images/samples/ilford-black-and-white.png" alt="Ilford black-and-white sample photo of the San Francisco skyline" width="480">

_Ilford B&W — ISO 100, 1/835 s._

<img src="images/samples/cinestill-800t.png" alt="CineStill 800T sample photo of the San Francisco skyline" width="480">

_CineStill 800T — ISO 100, 1/880 s._

## Features

- Live preview with film simulation profiles
- Larger inset controls for film profile, metering, EV, white balance, and photo resolution
- Physical shutter button on GPIO26
- Hold button for shutter set mode, short press to capture or cycle shutter speed
- Tap-to-zoom focus targeting with 1x / 2x / 4x zoom
- Focus peaking overlay for manual framing
- On-demand focus peaking, a translucent screen shutter, and a sleep button
- Long-press a profile to make it the boot default
- Pro-Mist bloom effect toggle for shoot-mode output
- Capture to `/home/pi/Pictures` (`camera.py` uses PNG; the Pi Zero path uses quality-92 JPEG)

## Film Simulations

The script includes the following film simulation profiles:

- Standard
- Classic Chrome
- Kodak Portra
- Fuji Velvia
- Fuji Astia
- Ilford B&W
- Kodak Gold
- CineStill 800T
- Warm Natural, Golden Daylight, and Soft Nostalgia

The Pi Zero script has all of the profiles above except CineStill 800T. The three warm profiles use restrained color shifts and light tone changes to keep skin and whites natural. They are inspired by the [Fuji X Weekly recipe collection](https://fujixweekly.com/2026/08/03/top-26-most-popular-fujifilm-recipes-of-2026-so-far-summer-edition/), without copying a particular recipe.

## Hardware

### Raspberry Pi Zero Build

- Raspberry Pi Zero 2 W recommended; this build uses an original Raspberry Pi Zero W because of price surges and availability
- Official Raspberry Pi HQ Camera (IMX477) and a compatible Pi Zero camera ribbon cable
- 6mm M12 mount lens, or a compatible C-mount HQ camera and lens
- Compatible GPIO touchscreen display
- [UPS-Lite for Raspberry Pi Zero](https://www.tindie.com/products/rachel/ups-lite-for-raspberry-pi-zero/) for battery power
- The UPS-Lite enclosure from the [UPS-Lite 3D files](https://github.com/linshuqin329/UPS-Lite)
- Any 3D-printed display housing that fits your display; you may need to add slits so the camera and display ribbon cables can pass through
- Momentary switch on GPIO 26 (optional; add a UI shutter button if one is not fitted)

### Raspberry Pi 5 Build

- Raspberry Pi 5
- Official Raspberry Pi HQ Camera (IMX477)
- 6mm M12 mount lens
- Optionally compatible with C mount HQ camera and C mount lenses
- 3.5" GPIO touchscreen display, 480x320 ([Setup Guide](https://www.reddit.com/r/raspberry_pi/comments/1bnav0y/i_finally_have_the_35inch_gpio_spi_lcd_working/))
- PD-compatible power bank
- Momentary Switch @ GPIO 26 (optional, create a UI shutter button if not using one)
- 3D-printed case assembled from [Thingiverse design 6571150](https://www.thingiverse.com/thing:6571150) and [Thingiverse design 4878249](https://www.thingiverse.com/thing:4878249), hot-glued together

## Installation

On Raspberry Pi OS Bookworm 64-bit:

```bash
sudo apt update && sudo apt install -y python3-pip python3-opencv libopencv-dev unclutter
pip3 install picamera2 gpiozero numpy simplejpeg --break-system-packages
```

## Setup

1. Place `camera.py` in `/home/pi` or the desired working directory.
   On a Pi Zero W or Pi Zero 2 W, use `camera-pi-zero.py` instead and update the service's `ExecStart` path below to match.
2. Ensure the picture folder exists:

```bash
mkdir -p /home/pi/Pictures
```

3. Create the service file:

```bash
sudo nano /etc/systemd/system/camera.service
```

Paste this content:

```ini
[Unit]
Description=HQ Camera
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/camera.py
WorkingDirectory=/home/pi
StandardOutput=journal
StandardError=journal
Restart=on-failure
RestartSec=5
User=pi
Environment=DISPLAY=:0
#Environment=SDL_VIDEODRIVER=fbcon
#Environment=SDL_FBDEV=/dev/fb1
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=WAYLAND_DISPLAY=wayland-1
Environment=DISPLAY=:0
Environment=LIBGL_ALWAYS_SOFTWARE=1

[Install]
WantedBy=multi-user.target
```

4. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera.service
sudo systemctl start camera.service
```

On the original Pi Zero W, full-resolution styled captures need a 128 MB contiguous-memory pool. Add this line under `[all]` in `/boot/firmware/config.txt`, then reboot:

```ini
dtoverlay=cma,cma-128
```

## Useful Commands

```bash
sudo systemctl status camera.service
sudo journalctl -u camera.service -f
sudo systemctl restart camera.service
sudo systemctl stop camera.service
```

## Usage

- Tap the on-screen `FILM` button to cycle film profiles.
- Hold the profile name for about 0.8 seconds to make it the boot default. A filled star marks the selected default; the choice is stored at `~/.config/rpi-film-camera/settings.json`.
- Tap the `Meter`, `EV`, and `WB` buttons to cycle metering, exposure compensation, and white balance.
- Tap `Photo: 12MP/3MP` to select the next still resolution; 12 MP is the default.
- Tap `PEAK` to show or hide same-frame focus peaking. It starts off for a faster preview.
- Tap the translucent round shutter button on the right to take a photo, including when the physical switch is unavailable.
- Tap `SLEEP` to stop the camera stream and blank the display; tap the display again to wake it.
- Tap the screen outside the UI to change the zoom anchor point and zoom level.
- Hold the GPIO26 button for shutter-set mode, then tap to cycle shutter speed.
- Short press the GPIO26 button to capture an image.

## Notes

The scripts write captures to `/home/pi/Pictures` with timestamped filenames including the selected film profile, ISO, and shutter speed. `camera.py` saves PNG files, while `camera-pi-zero.py` saves quality-92 JPEG files. Both log preview and capture phase timing. On Pi Zero, Standard and the three warm styles use fast planar-YUV JPEG encoding. Other styled shots convert one YUV capture array to BGR for processing.

Sample images and camera photos are included in the repository.

## Experimental Pi Zero console/display setup

`camera-pi-zero.py` is an experimental path for the original single-core Zero W. It uses an OpenCV fullscreen window in the desktop session and depends on the SPI display's kernel/DRM driver. The physical SPI refresh rate can remain the visible frame-rate ceiling even when the script's processing log reports a higher rate.

On the tested Pi Zero touchscreen, keep the `piscreen` overlay at `speed=18000000`. Higher SPI clocks caused corrupted colors and text. The 12 MP YUV still path also needs `dtoverlay=cma,cma-128` on that unit; reboot after editing `/boot/firmware/config.txt`.

The separate [rpi-simple-camera](https://github.com/prtk1910/rpi-simple-camera) project uses a 240×135 direct-SPI viewfinder with one physical button. It has the same ten styles but no touchscreen controls.

Useful device checks are:

```bash
cat /proc/fb
ls -l /dev/fb* /dev/dri/card* /dev/dri/renderD*
ls -l /sys/class/drm/
for status in /sys/class/drm/card*-*/status; do printf '%s: ' "$status"; cat "$status"; done
```

If the SPI panel is absent from these results, fix its overlay/driver setup before debugging the Python window. The exact overlay and device name depend on the panel vendor; use the display's setup guide and verify it after reboot.

The service environment shown above does not create a console-only renderer. Variables such as `DISPLAY`, `WAYLAND_DISPLAY`, `SDL_VIDEODRIVER`, or `SDL_FBDEV` do not make an OpenCV HighGUI window write directly to a framebuffer. A true no-desktop implementation would need a separate direct framebuffer or DRM/KMS renderer plus touch input read and calibrated through `evdev`; that architecture is outside the current script.
