# Cross-file fixture: schema defines NUMBER(38,0) — mismatches int cast above
# Also contains SQL injection via f-string interpolation

def create_tables(conn, config):
    archive_table = config["archive_table"]   # comes from job params — not validated
    error_table = config["error_table"]

    # BUG: SQL injection — table names interpolated directly from config
    create_archive_sql = f"CREATE TABLE IF NOT EXISTS {archive_table} (ROWID NUMBER(38,0), DATA VARIANT);"
    create_error_sql   = f"CREATE TABLE IF NOT EXISTS {error_table}   (ROWID NUMBER(38,0), DATA VARIANT);"

    conn.cursor().execute(create_archive_sql)
    conn.cursor().execute(create_error_sql)
