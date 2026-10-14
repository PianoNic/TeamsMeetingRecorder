import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import { theme, useOpenapi } from 'vitepress-openapi/client'
import 'vitepress-openapi/dist/style.css'
import './custom.css'

import spec from '../../public/openapi.json' with { type: 'json' }

// There is no public instance: the bot records whatever meeting it is sent to, so it only runs on
// your own machine or server. The playground points at a local one, and `allowCustomServer` lets
// you enter your own address instead.
const specWithServers = {
  ...spec,
  servers: [{ url: 'http://localhost:8000', description: 'A local TeamsRecorder' }],
}

// vitepress-openapi 0.2.4 starts the playground in "custom server" mode when custom servers are
// allowed, but the server-rendered page has no localStorage and renders the dropdown, which the
// browser reports as a hydration mismatch. Seed the flag to the dropdown, only when unset, so a
// reader who picked "Custom Server" keeps that choice.
function preferServerDropdown() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage.getItem('--oa-use-custom-server') === null) {
      localStorage.setItem('--oa-use-custom-server', 'false')
    }
  } catch {
    // Private windows and blocked site data throw on access; the default is harmless either way.
  }
}

export default {
  extends: DefaultTheme,
  async enhanceApp({ app }) {
    preferServerDropdown()
    useOpenapi({
      spec: specWithServers,
      config: {
        server: { allowCustomServer: true },
        // The generated samples stay empty in vitepress-openapi 0.2.4; the guides carry curl examples.
        operation: { hiddenSlots: ['code-samples'] },
      },
    })
    theme.enhanceApp({ app })
  },
} satisfies Theme
