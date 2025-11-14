CREATE FUNCTION jsonb_subtract(arg1 jsonb, arg2 jsonb) RETURNS jsonb AS $$
SELECT
    COALESCE(
        json_object_agg(
            KEY,
            CASE WHEN new_type = 'object' AND old_type = 'object'
                THEN jsonb_subtract(new_value, old_value)
            ELSE new_value END
        ),
        '{}'
    )::jsonb
FROM (
        SELECT KEY, VALUE AS new_value, jsonb_typeof(VALUE) AS new_type
        FROM jsonb_each(arg1::jsonb)
    ) AS NEW
    ${jsonb_subtract_join_type} OUTER JOIN (
        SELECT KEY, VALUE AS old_value, jsonb_typeof(VALUE) AS old_type
        FROM jsonb_each(arg2::jsonb)
    ) AS OLD
    USING (KEY)
WHERE new_value IS DISTINCT FROM old_value
$$ LANGUAGE SQL;