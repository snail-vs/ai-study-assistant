# Course section navigation availability

## Goal

Make unfinished course-outline sections visibly unavailable in the learning navigation and prevent frontend navigation into them.

## Implementation

1. Add shared frontend helpers for section readiness and generation-status labels.
2. Disable and label unavailable entries in `KnowledgeSidebar`.
3. Guard store-driven and URL-driven section selection, and make previous/next navigation target only available sections.
4. Add focused component/helper tests and run frontend validation.

## Ready rule

Sections with `generationStatus` equal to `completed` or `needs_attention` are available. All other statuses remain visible but cannot be selected.
