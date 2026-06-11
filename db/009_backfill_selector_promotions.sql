-- 009_backfill_selector_promotions.sql
--
-- Data backfill: promote APPROVED selector-class EEIs that were stranded by
-- the old promotion gate (`classifier_type in (email/phone/url/domain/ip)`),
-- which skipped human-tagged generic 'selector' EEIs. The code fix (db.py)
-- changes the gate to eei_class='selector' (excluding 'amount'); this
-- migration repairs rows approved BEFORE that fix.
--
-- Mirrors the logic of db._promotable_selector_subtype():
--   * eei_class must be 'selector'
--   * classifier_type 'amount' never promotes (case fact, not identifier)
--   * concrete types keep their subtype; everything else stores as 'other'
--
-- Idempotent: safe to re-run. ON CONFLICT respects UNIQUE(selector_type,value);
-- the UPDATE only touches rows whose promoted_selector_id is still NULL.

BEGIN;

-- 1. Create any missing selector_value rows for stranded approved EEIs.
INSERT INTO selector_value (selector_type, value, context, created_at)
SELECT DISTINCT
       CASE WHEN e.classifier_type IN ('email','phone','url','domain','ip')
            THEN e.classifier_type
            ELSE 'other'
       END                                                    AS selector_type,
       COALESCE(NULLIF(e.matched_value, ''), e.highlight_text) AS value,
       'from observation #' || e.observation_id               AS context,
       now()
FROM eei_candidate e
WHERE e.status = 'approved'
  AND e.eei_class = 'selector'
  AND e.classifier_type <> 'amount'
  AND e.promoted_selector_id IS NULL
  AND COALESCE(NULLIF(e.matched_value, ''), e.highlight_text) IS NOT NULL
ON CONFLICT (selector_type, value) DO NOTHING;

-- 2. Link each stranded EEI to its (now-existing) selector row.
UPDATE eei_candidate e
SET    promoted_selector_id = sv.selector_id
FROM   selector_value sv
WHERE  e.status = 'approved'
  AND  e.eei_class = 'selector'
  AND  e.classifier_type <> 'amount'
  AND  e.promoted_selector_id IS NULL
  AND  sv.selector_type = CASE WHEN e.classifier_type IN ('email','phone','url','domain','ip')
                               THEN e.classifier_type
                               ELSE 'other'
                          END
  AND  sv.value = COALESCE(NULLIF(e.matched_value, ''), e.highlight_text);

COMMIT;

-- Verify:
--   SELECT selector_type, value, context FROM selector_value ORDER BY selector_type, value;
--   SELECT eei_id, classifier_type, highlight_text, promoted_selector_id
--   FROM eei_candidate WHERE eei_class='selector' AND status='approved';
