import eslint from '@eslint/js'
import vue from 'eslint-plugin-vue'
import globals from 'globals'
import typescriptParser from '@typescript-eslint/parser'

export default [
  { ignores: ['dist/**', 'src/api/generated/**'] },
  eslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.{js,ts,vue}'],
    languageOptions: {
      parserOptions: { parser: typescriptParser },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/no-mutating-props': 'off',
      'no-empty': 'off',
      'no-unused-vars': ['warn', { args: 'none' }],
    },
  },
  {
    files: ['**/*.ts'],
    languageOptions: {
      parser: typescriptParser,
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      // TypeScript type names (for example RequestInit) are not runtime globals.
      'no-undef': 'off',
    },
  },
]
