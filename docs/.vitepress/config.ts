import { defineConfig } from 'vitepress'

const site = 'https://docs.teamsrecorder.pianonic.ch'

// Docs site for TeamsRecorder, built from the markdown in this folder. Served at the domain root,
// so no `base` is needed. Build: `vitepress build` (output: .vitepress/dist).
export default defineConfig({
  title: 'TeamsRecorder',
  description: 'A bot that joins Microsoft Teams meetings, records the audio and tells you when it is done.',
  lastUpdated: true,
  cleanUrls: true,
  // Links to http://localhost:8000 point at the reader's own instance; every other link is checked.
  ignoreDeadLinks: 'localhostLinks',
  // Absolute, because a link preview is rendered by a crawler that has no page to resolve a
  // relative path against.
  head: [
    ['link', { rel: 'icon', href: '/favicon.svg' }],
    ['meta', { name: 'theme-color', content: '#4B3FD1' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:image', content: `${site}/og-image.png` }],
    ['meta', { property: 'og:url', content: `${site}/` }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
  ],
  sitemap: { hostname: site },
  themeConfig: {
    logo: '/favicon.svg',
    nav: [
      { text: 'Getting started', link: '/getting-started' },
      {
        text: 'Guides',
        items: [
          { text: 'How a session works', link: '/how-it-works' },
          { text: 'Self-hosting', link: '/self-hosting' },
          { text: 'Configuration', link: '/configuration' },
          { text: 'Webhooks', link: '/webhooks' },
          { text: 'Microphone', link: '/microphone' },
        ],
      },
      { text: 'Development', link: '/development' },
    ],
    sidebar: [
      {
        text: 'Introduction',
        items: [
          { text: 'Getting started', link: '/getting-started' },
          { text: 'How a session works', link: '/how-it-works' },
          { text: 'Consent and privacy', link: '/privacy' },
        ],
      },
      {
        text: 'Running it',
        items: [
          { text: 'Self-hosting', link: '/self-hosting' },
          { text: 'Configuration', link: '/configuration' },
        ],
      },
      {
        text: 'Using it',
        items: [
          { text: 'Webhooks', link: '/webhooks' },
          { text: 'Microphone', link: '/microphone' },
        ],
      },
      {
        text: 'Contributing',
        items: [
          { text: 'Development', link: '/development' },
        ],
      },
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/PianoNic/TeamsRecorder' },
    ],
    search: { provider: 'local' },
    editLink: {
      pattern: 'https://github.com/PianoNic/TeamsRecorder/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    footer: {
      message: 'Released under the MIT License. Not affiliated with Microsoft.',
      copyright: 'TeamsRecorder by PianoNic',
    },
  },
})
