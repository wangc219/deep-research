"""用户 UID 可变更约束；重建相关外键并保留现有删除策略。"""

USER_UID_SCHEMA_STATEMENTS = (
    """
    DO $$
    DECLARE
        constraint_row RECORD;
    BEGIN
        FOR constraint_row IN
            SELECT
                constraint_info.conrelid::regclass AS table_name,
                constraint_info.conname,
                pg_get_constraintdef(constraint_info.oid) AS definition
            FROM pg_constraint AS constraint_info
            WHERE constraint_info.contype = 'f'
              AND constraint_info.confupdtype <> 'c'
              AND (
                  EXISTS (
                      SELECT 1
                      FROM unnest(constraint_info.conkey) AS column_number
                      JOIN pg_attribute AS attribute
                        ON attribute.attrelid = constraint_info.conrelid
                       AND attribute.attnum = column_number
                      WHERE attribute.attname IN ('uid', 'owner_uid')
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM unnest(constraint_info.confkey) AS column_number
                      JOIN pg_attribute AS attribute
                        ON attribute.attrelid = constraint_info.confrelid
                       AND attribute.attnum = column_number
                      WHERE attribute.attname = 'uid'
                  )
              )
        LOOP
            EXECUTE format(
                'ALTER TABLE %s DROP CONSTRAINT %I',
                constraint_row.table_name,
                constraint_row.conname
            );
            EXECUTE format(
                'ALTER TABLE %s ADD CONSTRAINT %I %s ON UPDATE CASCADE',
                constraint_row.table_name,
                constraint_row.conname,
                constraint_row.definition
            );
        END LOOP;
    END $$
    """,
)
