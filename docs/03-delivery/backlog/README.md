# Backlog Guide

## Purpose
- Store discussion TODOs that are not urgent enough to implement now.
- Keep long-term memory for ideas, risks, and deferred improvements.
- Provide a clean bridge from discussion -> backlog -> spec task.

## Structure
- `docs/03-delivery/backlog/TODO-index.md`: global list and status board.
- `docs/03-delivery/backlog/items/BLG-template.md`: template for new backlog items.
- `docs/03-delivery/backlog/items/BLG-xxxx.md`: one detailed card per item.

## ID Rule
- Format: `BLG-0001`, `BLG-0002`, ...
- IDs are monotonic and never reused.

## Status
- `inbox`: captured, not yet discussed.
- `discussing`: under active discussion.
- `parking`: intentionally deferred.
- `ready_for_spec`: clear enough to become an `XTR-xxx` task.
- `implemented`: delivered in code.
- `closed`: no longer needed.

## Workflow
1. Create a new card from `BLG-template.md` as `BLG-xxxx.md`.
2. Add one row into `TODO-index.md`.
3. During each discussion, update:
   - decision summary
   - trigger condition
   - status
4. When implementation starts, link the corresponding `XTR-xxx`.
5. After delivery, mark `implemented` or `closed`.

## Update Discipline
- Do not delete old items; update status instead.
- Keep index short; put details in each item card.
- Add related links: spec/validation/code paths/session note anchors.
