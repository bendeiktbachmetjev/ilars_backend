-- Если в таблице patients стоит ограничение (CHECK constraint) на колонку status,
-- которое позволяет только 'active' и 'inactive', то мы его удаляем и добавляем новое,
-- включающее 'dead'. 
--
-- Примечание: имена constraint могут отличаться в вашей БД, 
-- поэтому мы пытаемся дропнуть самое вероятное имя 'patients_status_check'.
-- Если у вас другое имя, вам нужно будет найти его или просто довериться валидации на бэкенде.

DO $$
BEGIN
    -- Попытка удалить типичные имена constraint для колонки status
    ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_status_check;
    ALTER TABLE patients DROP CONSTRAINT IF EXISTS check_status;
    ALTER TABLE patients DROP CONSTRAINT IF EXISTS status_check;
EXCEPTION
    WHEN undefined_object THEN
        -- Игнорируем ошибку если constraint не существует
        NULL;
END $$;

-- Добавляем новое правильное ограничение
ALTER TABLE patients ADD CONSTRAINT patients_status_check CHECK (status IN ('active', 'inactive', 'dead'));
