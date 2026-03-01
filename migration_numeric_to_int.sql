-- Migration to convert questionnaire numeric fields to smallint

-- daily_entries table
ALTER TABLE daily_entries
  ALTER COLUMN bloating TYPE SMALLINT USING ROUND(bloating)::SMALLINT,
  ALTER COLUMN impact_score TYPE SMALLINT USING ROUND(impact_score)::SMALLINT,
  ALTER COLUMN activity_interfere TYPE SMALLINT USING ROUND(activity_interfere)::SMALLINT;

-- monthly_entries table
ALTER TABLE monthly_entries
  ALTER COLUMN avoid_travel TYPE SMALLINT USING ROUND(avoid_travel)::SMALLINT,
  ALTER COLUMN avoid_social TYPE SMALLINT USING ROUND(avoid_social)::SMALLINT,
  ALTER COLUMN embarrassed TYPE SMALLINT USING ROUND(embarrassed)::SMALLINT,
  ALTER COLUMN worry_notice TYPE SMALLINT USING ROUND(worry_notice)::SMALLINT,
  ALTER COLUMN depressed TYPE SMALLINT USING ROUND(depressed)::SMALLINT,
  ALTER COLUMN control TYPE SMALLINT USING ROUND(control)::SMALLINT,
  ALTER COLUMN satisfaction TYPE SMALLINT USING ROUND(satisfaction)::SMALLINT;
