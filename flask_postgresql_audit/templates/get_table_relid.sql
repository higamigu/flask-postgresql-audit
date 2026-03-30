CREATE OR REPLACE FUNCTION get_table_relid(tablename text) RETURNS oid AS $$
SELECT tablename::regclass::oid;
$$ LANGUAGE SQL;
    