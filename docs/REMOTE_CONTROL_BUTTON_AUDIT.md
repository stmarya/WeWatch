# Participant and Remote Control button audit

## Root cause

Six dynamic controls interpolated `escapeJsString(...)` into a double-quoted `onclick` HTML attribute. `escapeJsString` correctly returns a JSON string wrapped in double quotes, but those quotes terminated the HTML attribute when assigned through `innerHTML`.

Example of the generated broken markup:

```html
<button onclick="openRemoteControlModal("client-1", "Client")">
```

The browser parsed the handler as `openRemoteControlModal(`, so clicking the control could not call its function. JavaScript syntax validation did not detect this because the template literal itself was valid JavaScript; the failure occurred only after the browser parsed the generated HTML.

## Controls reviewed

| Surface | Control | Result after fix |
| --- | --- | --- |
| Video tile | Remote Control & Assist Client | Opens the target-specific remote modal |
| Video tile | Capture snapshot evidence | Calls snapshot capture and reports when video is not ready |
| Video tile | Spotlight / Pin | Pins or unpins the selected tile |
| Video tile | Mute participant | Emits `admin_mute_client` for the selected client |
| Video tile | Remove participant | Confirms and emits `admin_kick_client` |
| Participants drawer | Mute / Pin / Remove | Uses the same central dispatcher and selected participant ID |

## Implementation

- Replaced dynamic inline `onclick` attributes with `data-client-action` and scoped event listeners.
- Added one `handleClientControlAction` dispatcher for tile and participant-list controls.
- Stops click propagation so a control click cannot accidentally trigger remote mouse takeover on the tile.
- Keeps action buttons above the annotation canvas and visible for keyboard/touch interaction.
- Appends the tile before initializing the annotation canvas, fixing its prior 0×0 initial size.
- Rejects remote, mute, and remove actions with visible feedback when signaling is disconnected.
- Resets pointer, annotation, and mouse-takeover state when the remote modal closes.

## Backend review

The signaling server already implements and authorizes the required events:

- `admin_mute_client`
- `admin_kick_client`
- `admin_remote_pointer`
- `admin_remote_annotate`
- `admin_remote_command`
- Desktop mouse, keyboard, scroll, and quick-action events

No signaling protocol change was required for this defect.

## Regression coverage

- Static contract rejects future `escapeJsString` interpolation inside inline `onclick` attributes.
- Unit tests require all five delegated tile actions and verify canvas setup order.
- Headless Chromium test clicked all five tile actions and all three participant-drawer actions.
- Browser result: Remote modal opened, Pin toggled, Mute/Kick emitted the correct target, and annotation canvas initialized with non-zero dimensions.
