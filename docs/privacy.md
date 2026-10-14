# Consent and privacy

TeamsRecorder records people talking. That is personal data almost everywhere, and in many places recording a conversation without consent is a criminal offence. The software cannot get consent for you, so this part is on whoever runs it.

::: danger Before you record
- **Tell everyone** in the meeting that it is being recorded, ideally in the invitation and again at the start.
- **Get their consent.** The bot joins under the name you give it; a clear name like *Recording Bot* helps, but it does not replace asking.
- **Follow the law that applies to you and your participants**, for example the GDPR in the EU, the Swiss FADP, or state wiretapping laws in the US, some of which require consent from every party.
:::

## What the bot keeps

- **Audio only.** No video, no screen sharing, no chat messages, no participant list.
- **One file per session**, in the storage you configure. Nothing is sent anywhere else.
- **Logs** contain session ids and statuses, not the meeting link, which carries ids of the organiser's tenant and account.

Deleting recordings is up to you: the bot never reads or removes a file once it has handed it over.

## Securing the API

Anyone who can reach the API can send the bot into a meeting or end a recording. Never expose it to the internet without a token:

```dotenv
BOT_ACCESS_TOKEN=a-long-random-value
```

Every endpoint except the health check (`/`) and live-audio ingest URLs (which carry their own secret) then requires `Authorization: Bearer <token>` or an `X-API-Key: <token>` header.

Protect the webhooks the same way: set `WEBHOOK_SECRET`, and have your receiver check the `X-Webhook-Secret` header.

## Not affiliated with Microsoft

TeamsRecorder joins meetings through the Teams web client like any guest in a browser. It is not made, endorsed or supported by Microsoft. Teams can change its web client at any time, which can break joining until the bot is updated.
