export type CourseSection = { generationStatus?: string | null }

const AVAILABLE_SECTION_STATUSES = new Set(['completed', 'needs_attention'])

export function isSectionAvailable(section: CourseSection | null | undefined) {
  return Boolean(section && AVAILABLE_SECTION_STATUSES.has(section.generationStatus || 'completed'))
}

export function sectionGenerationLabel(section: CourseSection | null | undefined) {
  const labels: Record<string, string> = {
    pending: '待生成',
    generating: '生成中',
    reviewing: '审核中',
    failed: '生成失败',
  }
  return labels[section?.generationStatus || ''] || '未生成'
}

export function findAvailableSectionIndex(
  sections: CourseSection[] | null | undefined,
  startIndex = 0,
  direction: 1 | -1 = 1,
) {
  if (!sections?.length) return -1
  for (let index = startIndex; index >= 0 && index < sections.length; index += direction) {
    if (isSectionAvailable(sections[index])) return index
  }
  return -1
}
