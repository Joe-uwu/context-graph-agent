# notification-service

Consumes `reasoning.produced` and routes notifications: fingerprint dedup, an interrupt bar
(above it a human is paged via Slack, below it items fold into a digest), and bundling so one
incident cluster raises one alert. Consumes `user.actions` to suppress acked/dismissed
targets. Emits `notifications.sent`. Serves the feed and action intake over HTTP.

## Topics

- Consumes: `reasoning.produced`, `user.actions`
- Produces: `notifications.sent`

## HTTP surface

Port `8007` (override with `CORTEX_HTTP_PORT`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` `/ready` `/metrics` | Ops |
| GET | `/api/v1/notifications` | Routed feed, highest risk first |
| POST | `/api/v1/actions` | Record a user action (`{action, target_id, actor}`) |
| GET | `/api/v1/stats` | Feed size |

`action` is one of `ack`, `dismiss`, `snooze`. `ack`/`dismiss` suppress future alerts for
the target and publish a `user.actions` event.

## Configuration

`CORTEX_RUNTIME`, `CORTEX_KAFKA_BOOTSTRAP`, `CORTEX_INTERRUPT_AT` (default `0.75`),
`CORTEX_HTTP_PORT` (default `8007`), `CORTEX_OTEL_ENDPOINT`.

## Run

```bash
CORTEX_HTTP_PORT=8007 python -m cortex.services.notification.main
docker build -f services/notification-service/Dockerfile -t cortex/notification-service .
docker run -p 8007:8007 cortex/notification-service
```

## Metrics

`cortex_events_processed_total{service="notification-service"}`,
`cortex_notifications_sent_total{channel}`, plus the shared HTTP metrics.

## Tests

```bash
pytest tests/services/test_notification_service.py
```
