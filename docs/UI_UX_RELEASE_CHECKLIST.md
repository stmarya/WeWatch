# WeWatch UI/UX release checklist — phases 4–6

## Automated release gates

The pull request must pass:

- Python unit tests and source compilation.
- Inline Jinja template JavaScript syntax validation.
- UI contract validation (`python tools/check_ui_contracts.py`).
- Whitespace validation.

The UI contract gate protects unique IDs, explicit button types, labelled form controls, dialog semantics, primary landmarks, monitoring overview IDs, overlay placement, Indonesian page language, responsive breakpoints, keyboard focus, reduced motion, and removal of legacy Google Meet branding.

## Manual runtime matrix

| Area | Normal | Empty/error | Compact/mobile |
| --- | --- | --- | --- |
| Admin login | Valid token enters dashboard | Invalid token is announced | 390px, keyboard visible |
| Camera | Feed and AI overlay load | Permission denied / camera unavailable | Tile remains within viewport |
| Monitoring overview | Status updates from `/status_data` | Endpoint failure does not break controls | Summary follows video in reading order |
| Incident state | Away, drowsy, phone, unknown face, posture | Clear state returns to normal | Headline and action remain visible |
| Participants | Join, leave, count update | No participants | Drawer behaves as bottom sheet |
| Messages | Send and receive | Empty conversation | Input stays above bottom bar |
| AI modules | Toggle each category | Backend rejection shows feedback | Category navigation scrolls internally |
| Meeting tools | Captions, reaction, whiteboard, share, record | Permission/API rejection | Available through More menu |
| Remote control | Selected client opens target-specific dialog | Disconnected target blocks action | Dialog scrolls; dangerous actions remain distinguishable |
| Gallery | Images open in a new tab | Empty state is clear | One-column grid |

## Keyboard and accessibility checks

- Tab order starts at the header and remains logical.
- Focus is visible on every control.
- Enter/Space activates buttons.
- Escape closes the active dialog or drawer.
- Tab and Shift+Tab remain inside an open dialog.
- Focus returns to the dialog trigger after closing.
- Icon-only buttons expose an accessible name.
- Alerts and incident changes are announced without stealing focus.
- Content remains usable at 200% zoom.

## Viewports

- Desktop: 1440×900 and 1280×800.
- Compact desktop/tablet: 1024×768 and 768×1024.
- Mobile: approximately 390×844.

## No-go conditions

Do not merge when any of these are present:

- Camera/WebRTC regression.
- Duplicate DOM IDs or JavaScript syntax failure.
- Horizontal page scrolling at mobile width.
- Critical action hidden outside the viewport.
- Dialog without keyboard escape/focus containment.
- Remote-control action sent to an unselected or stale target.
- Monitoring status contradicts the underlying API payload.

## Rollback

The implementation is split into phase commits. Revert the latest phase commit first. If a runtime regression remains, revert the hierarchy implementation PR and restore the prior `templates/index.html` and `static/gmeet.css` together so DOM/CSS contracts stay aligned.
