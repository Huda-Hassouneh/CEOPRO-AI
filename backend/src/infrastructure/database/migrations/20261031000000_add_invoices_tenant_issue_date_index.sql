-- Every sales screen filters a company's invoices by date (revenue windows on the dashboard and metrics, the
-- demand overview, reports, the first-sale date), but invoices was indexed only by (tenant, number) and
-- (tenant, id), so each of those queries read all of the company's invoices. Measured on 53,000 invoices:
-- MIN(issue_date) 23 ms -> 0.1 ms, a 60-day revenue window 23 ms -> 14 ms.
CREATE INDEX IF NOT EXISTS idx_invoices_tenant_issue_date
    ON invoices (tenant_id, issue_date);
