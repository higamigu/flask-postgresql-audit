CREATE OR REPLACE FUNCTION get_pk_values(relid oid, row_data jsonb) RETURNS jsonb AS $$
    DECLARE
        pk_columns text [];
        pk_values jsonb;
    BEGIN
        SELECT array_agg(a.attname ORDER BY a.attnum) INTO pk_columns
        FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = relid
            AND i.indisprimary;

        IF pk_columns IS NULL THEN
            RETURN '{}'::jsonb;
        END IF;

        SELECT jsonb_agg(row_data->>col) INTO pk_values
        FROM unnest(pk_columns) AS col;

        RETURN pk_values;
    END;
$$ LANGUAGE plpgsql;