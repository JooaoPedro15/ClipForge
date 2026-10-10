import { describe, expect, test } from 'vitest'

import { pageMeta } from '@/App'
import { tools } from '@/components/layout/Rail'

describe('ClipForge editing scope', () => {
  test('exposes only editing tools in the shell navigation and route metadata', () => {
    expect(tools.map((tool) => tool.id)).toEqual(['subtitle-forge', 'clip-splitter', 'cortes'])
    expect(Object.keys(pageMeta)).toEqual(['subtitle-forge', 'clip-splitter', 'cortes'])
  })
})
