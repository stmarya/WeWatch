# WeWatch UI/UX implementation — phases 0–3

## Scope

This implementation stabilizes the dashboard shell and establishes a monitoring-first hierarchy without changing camera, WebRTC, AI feature APIs, or remote-control command behavior.

## Phase 0 — baseline and guardrails

### Protected runtime contracts

The existing DOM IDs used by polling and WebRTC remain available. In particular, telemetry IDs (`stat-*`), client tile IDs, drawer IDs, modal IDs, and existing event-handler function names are preserved.

### Critical states to regression-test

| State | Expected result |
| --- | --- |
| Monitoring normal | Overview reports a safe state and no active incident |
| User away | Presence changes to Away and an attention incident appears |
| Drowsiness detected | Critical state and latest incident are visible |
| Phone detected | Security summary requests review |
| Unknown face | Security summary requests review |
| Poor posture | Attention state is visible without opening a drawer |
| No connected clients | Admin feed remains usable; participants panel is empty |
| Client joins/leaves | Grid and participant count update as before |
| Drawer open | Overview yields space to the requested drawer |
| Remote control | Remains gated behind a selected participant tile |

### Viewport baseline

Validate at 1440px desktop, 1024px tablet/compact desktop, 768px tablet, and approximately 390px mobile.

## Phase 1 — structural foundation

- Fixed the missing bottom-bar closing boundary so overlays and modals are no longer nested inside the control bar.
- Added semantic header, main, navigation, aside, and section landmarks.
- Added explicit button types and focus-visible treatment.
- Added reduced-motion handling.
- Preserved existing IDs and backend endpoints.

## Phase 2 — dashboard hierarchy MVP

- Added a persistent monitoring overview next to the camera stage.
- Added a five-signal risk summary: presence, focus, drowsiness, security, and posture.
- Added an incident summary populated from existing `/status_data` payloads and proctor alerts.
- Reduced the primary control bar to microphone, camera, snapshot, more, and leave.
- Kept secondary meeting tools available in the More menu.
- Changed the initial state to the overview instead of opening AI modules automatically.

## Phase 3 — navigation and feature grouping

- Added product-level navigation for Overview, Participants, Messages, AI Modules, and Meeting Safety.
- Added sticky category shortcuts for Productivity, Security, Health, Gestures, and Extras.
- Preserved remote control gating through participant selection.
- Added responsive behavior: stacked overview at tablet/mobile widths and bottom-sheet drawers below 900px.

## Acceptance checklist

- [ ] Camera feed loads and toggles as before.
- [ ] `/status_data` updates both legacy telemetry and the new overview.
- [ ] No duplicate DOM IDs.
- [ ] Recording, whiteboard, captions, reactions, screen sharing, and settings remain reachable through More.
- [ ] People, chat, modules, host controls, and session details drawers still open and close.
- [ ] Remote control opens only from a client participant tile.
- [ ] No horizontal page overflow at 390px.
- [ ] Focus indicators are visible for keyboard navigation.
- [ ] No new JavaScript console errors.
