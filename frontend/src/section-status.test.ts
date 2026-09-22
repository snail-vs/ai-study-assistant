import { describe, expect, it } from 'vitest'
import { findAvailableSectionIndex, isSectionAvailable, sectionGenerationLabel } from './section-status'

describe('course section availability', () => {
  it('only exposes completed and attention-needed sections', () => {
    expect(isSectionAvailable({ generationStatus: 'completed' })).toBe(true)
    expect(isSectionAvailable({ generationStatus: 'needs_attention' })).toBe(true)
    expect(isSectionAvailable({ generationStatus: 'pending' })).toBe(false)
    expect(isSectionAvailable({ generationStatus: 'generating' })).toBe(false)
    expect(isSectionAvailable({ generationStatus: 'reviewing' })).toBe(false)
    expect(isSectionAvailable({ generationStatus: 'failed' })).toBe(false)
  })

  it('finds available sections in either navigation direction', () => {
    const sections = [
      { generationStatus: 'completed' },
      { generationStatus: 'generating' },
      { generationStatus: 'completed' },
    ]
    expect(findAvailableSectionIndex(sections, 1, 1)).toBe(2)
    expect(findAvailableSectionIndex(sections, 1, -1)).toBe(0)
    expect(findAvailableSectionIndex(sections, 3, 1)).toBe(-1)
  })

  it('provides labels for unfinished generation states', () => {
    expect(sectionGenerationLabel({ generationStatus: 'pending' })).toBe('待生成')
    expect(sectionGenerationLabel({ generationStatus: 'generating' })).toBe('生成中')
    expect(sectionGenerationLabel({ generationStatus: 'reviewing' })).toBe('审核中')
    expect(sectionGenerationLabel({ generationStatus: 'failed' })).toBe('生成失败')
  })
})
