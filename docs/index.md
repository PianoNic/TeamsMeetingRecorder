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
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M12 18a6 6 0 1 0 0-12a6 6 0 0 0 0 12m0-16C6.477 2 2 6.477 2 12s4.477 10 10 10s10-4.477 10-10S17.523 2 12 2M3.5 12a8.5 8.5 0 1 1 17 0a8.5 8.5 0 0 1-17 0"/></svg>'
    title: One call to record
    details: POST a meeting link to /join. The bot joins as a guest, records until the meeting is over and leaves on its own. No Teams app, no tenant registration.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M19.001 6.01a3.25 3.25 0 0 1 3 3.24v8a4.75 4.75 0 0 1-4.75 4.75h-8a3.25 3.25 0 0 1-3.24-3h1.51c.12.848.848 1.5 1.73 1.5h8a3.25 3.25 0 0 0 3.25-3.25v-8c0-.882-.652-1.609-1.5-1.73zM14.75 2A3.25 3.25 0 0 1 18 5.25v9.5A3.25 3.25 0 0 1 14.75 18h-9.5A3.25 3.25 0 0 1 2 14.75v-9.5A3.25 3.25 0 0 1 5.25 2zM3.5 14.75c0 .966.784 1.75 1.75 1.75h9.5a1.75 1.75 0 0 0 1.75-1.75V7.5h-13zM5.25 3.5A1.75 1.75 0 0 0 3.5 5.25V6h13v-.75a1.75 1.75 0 0 0-1.75-1.75z"/></svg>'
    title: Several meetings at once
    details: Every session gets its own browser and its own audio device, so recordings never bleed into each other.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M3.5 12a8.5 8.5 0 0 1 17 0v2h-2.25a.75.75 0 0 0-.75.75v6.5c0 .414.336.75.75.75H19a3 3 0 0 0 3-3v-7c0-5.523-4.477-10-10-10S2 6.477 2 12v7a3 3 0 0 0 3 3h.75a.75.75 0 0 0 .75-.75v-6.5a.75.75 0 0 0-.75-.75H3.5zm17 3.5V19a1.5 1.5 0 0 1-1.5 1.5v-5zM3.5 19v-3.5H5v5A1.5 1.5 0 0 1 3.5 19m9.25-7.25a.75.75 0 0 0-1.5 0v10.5a.75.75 0 0 0 1.5 0zm-4 2.25a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5a.75.75 0 0 1 .75-.75m7.25.75a.75.75 0 0 0-1.5 0v4.5a.75.75 0 0 0 1.5 0z"/></svg>'
    title: Clean, lossless audio
    details: 48 kHz straight from the browser, as WAV or as lossless FLAC at a fraction of the size.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M4 6c0-.69.315-1.293.774-1.78c.455-.482 1.079-.883 1.793-1.202C7.996 2.377 9.917 2 12 2s4.004.377 5.433 1.018c.714.32 1.338.72 1.793 1.202c.459.487.774 1.09.774 1.78v12c0 .69-.315 1.293-.774 1.78c-.455.482-1.079.883-1.793 1.203C16.004 21.623 14.083 22 12 22s-4.004-.377-5.433-1.017c-.714-.32-1.338-.72-1.793-1.203C4.315 19.293 4 18.69 4 18zm1.5 0c0 .207.09.46.365.75c.279.296.717.596 1.315.864c1.195.535 2.899.886 4.82.886s3.625-.35 4.82-.886c.598-.268 1.036-.568 1.315-.864c.275-.29.365-.543.365-.75s-.09-.46-.365-.75c-.279-.296-.717-.596-1.315-.864c-1.195-.535-2.9-.886-4.82-.886s-3.625.35-4.82.886c-.598.268-1.036.568-1.315.864c-.275.29-.365.543-.365.75m13 2.392c-.32.22-.68.417-1.067.59C16.004 9.623 14.083 10 12 10s-4.004-.377-5.433-1.018a7 7 0 0 1-1.067-.59V18c0 .207.09.46.365.75c.279.296.717.596 1.315.864c1.195.535 2.899.886 4.82.886s3.625-.35 4.82-.886c.598-.268 1.036-.568 1.315-.864c.275-.29.365-.543.365-.75z"/></svg>'
    title: Storage of your choice
    details: Local disk, Azure Blob Storage or any S3-compatible bucket, from AWS to Cloudflare R2 to your own server.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M5.694 12L2.299 3.272a.75.75 0 0 1 .942-.982l.093.039l18 9a.75.75 0 0 1 .097 1.284l-.097.058l-18 9c-.583.291-1.217-.245-1.065-.848l.03-.095zL2.299 3.272zM4.402 4.54l2.61 6.71h6.627a.75.75 0 0 1 .743.648l.007.102a.75.75 0 0 1-.649.743l-.101.007H7.01l-2.609 6.71L19.322 12z"/></svg>'
    title: Webhooks that arrive
    details: A POST when a session ends and, if you like, at every step on the way. Retried until delivered, even across restarts.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M3 5.75A.75.75 0 0 1 3.75 5c2.663 0 5.258-.943 7.8-2.85a.75.75 0 0 1 .9 0C14.992 4.057 17.587 5 20.25 5a.75.75 0 0 1 .75.75V11q0 .507-.04.996a6.5 6.5 0 0 0-1.465-.684q.005-.155.005-.312V6.478c-2.577-.152-5.08-1.09-7.5-2.8c-2.42 1.71-4.923 2.648-7.5 2.8V11c0 4.149 2.332 7.221 7.125 9.285a6.5 6.5 0 0 0 1.005 1.52l-.355.143a.75.75 0 0 1-.55 0C5.958 19.676 3 16 3 11zM23 17.5a5.5 5.5 0 1 1-11 0a5.5 5.5 0 0 1 11 0m-2.146-2.354a.5.5 0 0 0-.708 0L16.5 18.793l-1.646-1.647a.5.5 0 0 0-.708.708l2 2a.5.5 0 0 0 .708 0l4-4a.5.5 0 0 0 0-.708"/></svg>'
    title: Nothing gets lost
    details: A session cut off by a crash or a restart is reported on the next start, together with everything it recorded until then.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M16.25 5.18a.75.75 0 0 0 .142 1.051a7.251 7.251 0 0 1-3.599 12.976l.677-.677a.75.75 0 0 0-.977-1.133l-.084.073l-2 2a.75.75 0 0 0-.073.976l.073.084l2 2a.75.75 0 0 0 1.133-.976l-.072-.084l-.75-.75a8.75 8.75 0 0 0 4.581-15.68a.75.75 0 0 0-1.051.141m-5.72-3.71a.75.75 0 0 0 0 1.06l.75.75a8.75 8.75 0 0 0-4.85 15.47a.75.75 0 1 0 .956-1.157a7.251 7.251 0 0 1 3.82-12.8l-.676.677a.75.75 0 1 0 1.061 1.06l2-2a.75.75 0 0 0 0-1.06l-2-2a.75.75 0 0 0-1.06 0"/></svg>'
    title: Safe to retry
    details: Tag a join with your own reference, and a repeated /join returns the running session instead of sending a second bot.
  - icon: '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"><path fill="currentColor" d="M15 4.25c0-1.08-1.274-1.651-2.08-.935L8.427 7.31a.75.75 0 0 1-.498.19H4.25A2.25 2.25 0 0 0 2 9.748v4.497a2.25 2.25 0 0 0 2.25 2.25h3.68a.75.75 0 0 1 .498.19l4.491 3.993c.806.717 2.081.145 2.081-.934zM9.425 8.43L13.5 4.806v14.382l-4.075-3.623a2.25 2.25 0 0 0-1.495-.569H4.25a.75.75 0 0 1-.75-.75V9.748a.75.75 0 0 1 .75-.75h3.68a2.25 2.25 0 0 0 1.495-.568m9.567-2.533a.75.75 0 0 1 1.049.156A9.96 9.96 0 0 1 22 12a9.96 9.96 0 0 1-1.96 5.947a.75.75 0 1 1-1.205-.893A8.46 8.46 0 0 0 20.5 12a8.46 8.46 0 0 0-1.665-5.053a.75.75 0 0 1 .157-1.05m-1.849 2.472a.75.75 0 0 1 1.017.302c.536.991.84 2.125.84 3.329a7 7 0 0 1-.84 3.328a.75.75 0 0 1-1.32-.714c.42-.777.66-1.667.66-2.615a5.5 5.5 0 0 0-.66-2.614a.75.75 0 0 1 .303-1.016"/></svg>'
    title: It can speak, too
    details: Play a file or a live stream, for example text to speech, into the meeting through the bot's microphone.
---
