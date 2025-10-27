CREATE TRIGGER audit_trigger AFTER INSERT OR UPDATE OR DELETE ON ${table_name}
FOR EACH ROW
WHEN (${schema_prefix}get_setting('flask_pga.enable_audit', 'true')::bool)
EXECUTE PROCEDURE ${schema_prefix}create_activity(${excluded_columns})
