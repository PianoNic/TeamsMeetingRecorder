import { defineConfig } from 'vitepress'
import { minifyHtml, useSidebar } from 'vitepress-openapi'
import spec from '../public/openapi.json' with { type: 'json' }

const site = 'https://docs.teamsrecorder.pianonic.ch'

// The API reference is generated from the schema: one page per operation under /operations/,
// each with its own request playground. Path only in the sidebar, the badge already shows the verb.
const openapiSidebar = useSidebar({
  spec,
  linkPrefix: '/operations/',
  sidebarItemTemplate: ({ method, path }: { method: string, path: string }) => minifyHtml(`
    <span class="OASidebarItem group/oaOperationLink">
      <span class="OASidebarItem-badge OAMethodBadge--${method.toLowerCase()}">${method.toUpperCase()}</span>
      <span class="OASidebarItem-text text">${path}</span>
    </span>
  `),
})

// Docs site for TeamsRecorder, built from the markdown in this folder. Served at the domain root,
// so no `base` is needed. Build: `vitepress build` (output: .vitepress/dist).
export default defineConfig({
  title: 'TeamsRecorder',
  description: 'A bot that joins Microsoft Teams meetings, records the audio and tells you when it is done.',
  lastUpdated: true,
  cleanUrls: true,
  // The pages are also read on GitHub, where the generated API reference does not exist.
  ignoreDeadLinks: true,
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
  // Frontmatter cannot read a dynamic route's params, so the generated operation pages get their
  // browser title here, otherwise they all share the site title.
  transformPageData(pageData) {
    if (pageData.params?.pageTitle) {
      pageData.title = pageData.params.pageTitle
    }
  },
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
      { text: 'API', link: '/api' },
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
          { text: 'API overview', link: '/api' },
          { text: 'Webhooks', link: '/webhooks' },
          { text: 'Microphone', link: '/microphone' },
        ],
      },
      {
        text: 'API reference',
        collapsed: true,
        items: openapiSidebar.generateSidebarGroups({ linkPrefix: '/operations/' }),
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
