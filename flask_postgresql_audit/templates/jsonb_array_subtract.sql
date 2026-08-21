CREATE FUNCTION ${schema_prefix}jsonb_array_subtract(arg1 jsonb, arg2 jsonb) RETURNS jsonb AS $$
SELECT
    CASE
        WHEN jsonb_typeof(arg1) = 'array' THEN
            COALESCE(
                (
                    SELECT jsonb_agg(elem ORDER BY ord)
                    FROM jsonb_array_elements(arg1) WITH ORDINALITY AS t(elem, ord)
                    WHERE NOT (
                        CASE
                            WHEN arg2 IS NULL THEN FALSE
                            WHEN jsonb_typeof(arg2) = 'array' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM jsonb_array_elements(arg2) AS old_elem
                                    WHERE old_elem = elem
                                )
                            ELSE elem = arg2
                        END
                    )
                ),
                '[]'::jsonb
            )
        WHEN arg1 IS DISTINCT FROM arg2 THEN
            arg1
        ELSE
            NULL
    END
$$ LANGUAGE SQL;
