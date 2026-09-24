# WeWatch scale profile

This profile is the production path for rooms with hundreds of participants.
The current legacy WebRTC page remains available for local development, while
the scale profile provides the infrastructure needed for an SFU-based rollout.

## Run locally

1. Replace the LiveKit key and secret in `infra/livekit.yaml`.
2. Set `WEBRTC_SECRET_KEY` to a random value of at least 32 characters.
3. Configure a real public IP, DNS name, TLS certificate, and TURN credentials.
4. Start the media stack:

```bash
docker compose -f docker-compose.scale.yml up -d
```

Do not expose LiveKit or Coturn directly to the public internet without TLS,
firewall rules, rate limiting, and rotated credentials.

## Capacity policy

- A room may have 500+ connected participants.
- Each browser subscribes only to visible tiles.
- Default active video grid: 9 tiles.
- Other participants are audio-only or represented by an avatar.
- Use simulcast layers (180p/360p/720p) and active-speaker switching.
- Use Redis for signaling fan-out and room presence.

## Required production work

The SFU does not automatically migrate the existing raw
`RTCPeerConnection` UI. The client must use the LiveKit client SDK and receive
short-lived room tokens from an authenticated API. The legacy page should only
be used as a fallback until the new client is load-tested.

The signaling service now supports:

- `REDIS_URL` for Socket.IO fan-out and shared participant state;
- `WEBRTC_REQUIRE_JOIN_TOKEN=true` to require signed, short-lived client tokens;
- `POST /api/room-token` with `X-Admin-Token` to issue a client token;
- `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` to return a LiveKit JWT from the
  same endpoint;
- `/healthz` and `/readyz` for load balancers;
- `tools/load_test_signaling.py` for connection/join smoke tests.

When legacy token enforcement is enabled, pass `join_token` to the client as
`/client?join_token=<token>`. For the SFU client, use `livekit_token` with the
LiveKit client SDK. The token identity must match the participant identity.

Minimum release gates:

- 600 concurrent joins;
- 99% successful room joins;
- p95 signaling latency below 200 ms;
- first media below 5 seconds;
- reconnect success above 98%;
- packet loss and TURN relay dashboards enabled.