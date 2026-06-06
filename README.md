
# LG TV Control for Home Assistant

This custom integration allows you to control the picture settings and input source of your LG TV from Home Assistant.

## Installation

1.  **Copy the `lgtv` directory** into your Home Assistant `custom_components` directory.
2.  **Restart Home Assistant.**

## Configuration

1.  Go to **Settings > Devices & Services**.
2.  Click the **+ Add Integration** button.
3.  Search for **"LG TV Control"** and select it.
4.  Enter the **IP address** of your LG TV and click **Submit**.
5.  Follow the on-screen instructions to pair with your TV.

## Usage

Once configured, you will have a new `media_player` entity for your TV. This entity allows you to:

*   **Select Input Source:** Use the `source` attribute to change the HDMI input.
*   **Control Picture Settings:** Use the `lgtv.set_picture_settings` service.

### Automations

You can use the `lgtv.set_picture_settings` service in your automations to control the contrast and OLED brightness for a specific picture mode. You can also use the standard `media_player.select_source` service to change inputs.

**Example Automation (Set Picture Settings):**

```yaml
automation:
  - alias: "Set Cinema Mode at Night"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: lgtv.set_picture_settings
        target:
          entity_id: media_player.lg_tv_192_168_1_100
        data:
          picture_mode: "cinema"
          contrast: 80
          oled_brightness: 60
```

**Example Automation (Select HDMI Input):**

```yaml
automation:
  - alias: "Switch to PS5 Input"
    trigger:
      - platform: state
        entity_id: switch.ps5_power
        to: "on"
    action:
      - service: media_player.select_source
        target:
          entity_id: media_player.lg_tv_192_168_1_100
        data:
          source: "HDMI 4"
```
