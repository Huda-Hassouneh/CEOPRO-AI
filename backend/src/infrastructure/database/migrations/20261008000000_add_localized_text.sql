-- Language-aware names for products, categories and anything else stored as
-- a {"en": ..., "ar": ..., "fr": ...} JSONB object.
--
-- The language comes from the transaction-local setting app.lang, which the
-- backend sets on every tenant connection from the request's interface
-- language (src/infrastructure/request_language.py). Without it the function
-- behaves as English.
--
-- Fallback order:
--   ar: ar -> en -> fr -> any other value
--   en: en -> fr -> any non-Arabic value -> ar (only when it is the sole name)
--   fr: fr -> en -> any non-Arabic value -> ar
-- So the English interface never shows an Arabic name when any other name
-- exists, and the Arabic interface prefers the Arabic name.

CREATE OR REPLACE FUNCTION localized_text(value jsonb, lang text DEFAULT NULL)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    wanted text := lower(COALESCE(NULLIF(lang, ''), NULLIF(current_setting('app.lang', true), ''), 'en'));
    result text;
BEGIN
    IF value IS NULL THEN
        RETURN NULL;
    END IF;
    IF jsonb_typeof(value) = 'string' THEN
        RETURN value #>> '{}';
    END IF;
    IF jsonb_typeof(value) <> 'object' THEN
        RETURN value::text;
    END IF;

    result := NULLIF(btrim(value ->> wanted), '');
    IF result IS NOT NULL THEN
        RETURN result;
    END IF;

    IF wanted = 'ar' THEN
        result := COALESCE(NULLIF(btrim(value ->> 'en'), ''), NULLIF(btrim(value ->> 'fr'), ''));
    ELSE
        result := COALESCE(NULLIF(btrim(value ->> 'en'), ''), NULLIF(btrim(value ->> 'fr'), ''));
        IF result IS NULL THEN
            SELECT NULLIF(btrim(e.value), '') INTO result
            FROM jsonb_each_text(value) AS e
            WHERE e.key <> 'ar' AND NULLIF(btrim(e.value), '') IS NOT NULL
            ORDER BY e.key
            LIMIT 1;
        END IF;
    END IF;
    IF result IS NOT NULL THEN
        RETURN result;
    END IF;

    SELECT NULLIF(btrim(e.value), '') INTO result
    FROM jsonb_each_text(value) AS e
    WHERE NULLIF(btrim(e.value), '') IS NOT NULL
    ORDER BY (e.key = 'ar') DESC, e.key
    LIMIT 1;
    RETURN result;
END;
$$;

GRANT EXECUTE ON FUNCTION localized_text(jsonb, text) TO PUBLIC;
