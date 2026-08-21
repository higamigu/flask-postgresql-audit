CREATE FUNCTION ${schema_prefix}jsonb_diff(arg1 jsonb, arg2 jsonb) RETURNS jsonb AS $$
SELECT
    CASE
        WHEN jsonb_typeof(arg1) = 'array' AND jsonb_typeof(arg2) = 'array' THEN
            ${schema_prefix}jsonb_array_subtract(arg1, arg2)
        WHEN jsonb_typeof(arg1) = 'object' AND jsonb_typeof(arg2) = 'object' THEN
            COALESCE(
                (
                    SELECT json_object_agg(
                        KEY,
                        CASE
                            WHEN new_type = 'object' AND old_type = 'object'
                                THEN ${schema_prefix}jsonb_diff(new_value, old_value)
                            WHEN new_type = 'array' AND old_type = 'array'
                                THEN ${schema_prefix}jsonb_diff(new_value, old_value)
                            ELSE new_value
                        END
                    )
                    FROM (
                        SELECT KEY, VALUE AS new_value, jsonb_typeof(VALUE) AS new_type
                        FROM jsonb_each(arg1)
                    ) AS NEW
                    ${jsonb_subtract_join_type} OUTER JOIN (
                        SELECT KEY, VALUE AS old_value, jsonb_typeof(VALUE) AS old_type
                        FROM jsonb_each(arg2)
                    ) AS OLD
                    USING (KEY)
                    WHERE new_value IS DISTINCT FROM old_value
                )::jsonb,
                '{}'::jsonb
            )
        WHEN jsonb_typeof(arg1) = 'array' THEN
            ${schema_prefix}jsonb_array_subtract(arg1, arg2)
        WHEN jsonb_typeof(arg1) = 'object' AND (arg2 IS NULL OR jsonb_typeof(arg2) != 'object') THEN
            arg1
        WHEN arg1 IS DISTINCT FROM arg2 THEN
            arg1
        ELSE
            NULL
    END
$$ LANGUAGE SQL;

