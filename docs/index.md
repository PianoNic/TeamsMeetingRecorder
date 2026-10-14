---
layout: home

hero:
  name: TeamsRecorder
  text: Your bot in every Teams meeting
  tagline: Send it a meeting link. It joins as a guest, waits out the lobby, records the audio, leaves when the room empties and tells you where the file is.
  image:
    src: /favicon.svg
    alt: TeamsRecorder
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: How a session works
      link: /how-it-works
    - theme: alt
      text: GitHub
      link: https://github.com/PianoNic/TeamsRecorder

features:
  - icon: 🎙️
    title: One call to record
    details: POST a meeting link to /join. The bot joins as a guest, records until the meeting is over and leaves on its own. No Teams app, no tenant registration.
  - icon: 🧩
    title: Several meetings at once
    details: Every session gets its own browser and its own audio device, so recordings never bleed into each other.
  - icon: 🎧
    title: Clean, lossless audio
    details: 48 kHz straight from the browser, as WAV or as lossless FLAC at a fraction of the size.
  - icon: 🗄️
    title: Storage of your choice
    details: Local disk, Azure Blob Storage or any S3-compatible bucket, from AWS to Cloudflare R2 to your own server.
  - icon: 📬
    title: Webhooks that arrive
    details: A POST when a session ends and, if you like, at every step on the way. Retried until delivered, even across restarts.
  - icon: 🛟
    title: Nothing gets lost
    details: A session cut off by a crash or a restart is reported on the next start, together with everything it recorded until then.
  - icon: 🔁
    title: Safe to retry
    details: Tag a join with your own reference, and a repeated /join returns the running session instead of sending a second bot.
  - icon: 🔊
    title: It can speak, too
    details: Play a file or a live stream, for example text to speech, into the meeting through the bot's microphone.
---
