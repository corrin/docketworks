import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
    settings: {
      'import/resolver': {
        alias: {
          map: [['@', './src']],
          extensions: ['.ts', '.vue', '.js'],
        },
      },
    },
  },

  globalIgnores([
    '**/dist/**',
    '**/dist-ssr/**',
    '**/dist-manual/**',
    'manual/.vitepress/cache/**',
    '**/coverage/**',
    '**/scripts/**',
    '**/playwright-report/**',
    '**/test-results/**',
  ]),

  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  skipFormatting,
)
