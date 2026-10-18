-- Real bug found live in end-to-end acceptance testing: chk_email_format's
-- regex did not allow '+' in the local part, so a perfectly valid, common
-- real-world email (RFC 5321 sub-addressing, e.g. name+tag@gmail.com) was
-- rejected at signup with an unhandled CheckViolation - surfaced to the
-- user as a generic "Unable to connect" error, not even a clear validation
-- message. Widens the character class to include '+'; no other behavior
-- change.
ALTER TABLE users DROP CONSTRAINT chk_email_format;
ALTER TABLE users ADD CONSTRAINT chk_email_format
    CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');
