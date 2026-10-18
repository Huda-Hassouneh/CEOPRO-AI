import { useMemo, useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import Table from '../../../shared/components/ui/Table.jsx';
import { useSalesReport } from '../hooks/useSalesReport.js';
import { useFinancialSummaryReport } from '../hooks/useFinancialSummaryReport.js';
import { reportsApi } from '../api/reportsApi.js';
import { downloadAsFile } from '../utils/exportFile.js';
import '../styles/Reports.css';

const PAGE_SIZE = 50;

const SALES_COLUMNS = [
  { key: 'issue_date', header: 'issueDate' },
  { key: 'invoice_number', header: 'invoiceNumber' },
  { key: 'product_name', header: 'product' },
  { key: 'quantity', header: 'quantity' },
  { key: 'unit_price', header: 'unitPrice' },
  { key: 'total_price', header: 'total' },
  { key: 'line_gross_profit', header: 'grossProfit' },
];

export default function UnifiedReportsCenterPage() {
  const { t, locale, dir } = useI18n();
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [windowDays, setWindowDays] = useState(30);
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(null);
  const [exportFailed, setExportFailed] = useState(false);

  const range = {
    startDate: startDate ? new Date(startDate).toISOString() : undefined,
    // Exclusive end - add a day so the picked end date's own invoices are included.
    endDate: endDate ? new Date(new Date(endDate).getTime() + 86400000).toISOString() : undefined,
  };
  const salesQuery = useSalesReport({ ...range, limit: PAGE_SIZE, offset: page * PAGE_SIZE });
  const financialQuery = useFinancialSummaryReport({ windowDays });

  const currencyFormatter = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }), [locale]);
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);
  const formatAmount = (value) => (value === null || value === undefined ? t('reports.common.unknown') : currencyFormatter.format(value));
  const formatDate = (value) => dateFormatter.format(new Date(value));
  // Quantities are stored with 4 decimals; show only the ones that matter (2 kg, 1.25 kg).
  const formatQuantity = (value) => (value === null || value === undefined ? '' : new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(Number(value)));

  const sales = salesQuery.data;
  const financial = financialQuery.data;

  const tableRows = (sales?.rows || []).map((row) => ({
    ...row,
    issue_date: formatDate(row.issue_date),
    quantity: formatQuantity(row.quantity),
    unit_price: formatAmount(row.unit_price),
    total_price: formatAmount(row.total_price),
    line_gross_profit: row.has_cost_data ? formatAmount(row.line_gross_profit) : t('reports.sales.noCostData'),
  }));

  // Pages come from the server; total_row_count covers the whole period.
  const totalRows = sales?.total_row_count || 0;
  const pageCount = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  const firstRow = (sales?.offset || 0) + 1;

  const tableColumns = SALES_COLUMNS.map((col) => ({ ...col, header: t(`reports.sales.columns.${col.header}`), accessor: col.key }));

  const exportSales = async (format) => {
    setExporting(format);
    setExportFailed(false);
    const file = await reportsApi.exportSales({ format, lang: locale, ...range });
    setExporting(null);
    if (!file) {
      setExportFailed(true);
      return;
    }
    downloadAsFile(`keel-sales-report-${new Date().toISOString().slice(0, 10)}.${format}`, file,
      { csv: 'text/csv;charset=utf-8;', json: 'application/json', pdf: 'application/pdf' }[format]);
  };

  const exportFinancialJson = () => {
    if (!financial) return;
    downloadAsFile(`keel-financial-summary-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(financial, null, 2), 'application/json');
  };

  return <div className="reports-page" dir={dir}>
    <PageHeader title={t('reports.page.title')} subtitle={t('reports.page.subtitle')} />

    <Card className="reports-section">
      <div className="reports-section__header">
        <h2>{t('reports.financial.title')}</h2>
        <div className="reports-section__actions">
          <label htmlFor="reports-window-days">{t('reports.financial.windowLabel')}</label>
          <select id="reports-window-days" value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))} className="reports-select">
            <option value={7}>{t('reports.financial.windowOptions.7')}</option>
            <option value={30}>{t('reports.financial.windowOptions.30')}</option>
            <option value={90}>{t('reports.financial.windowOptions.90')}</option>
          </select>
          <Button size="sm" variant="outline" leadingIcon={<Download size={14} />} disabled={!financial} onClick={exportFinancialJson}>{t('reports.common.exportJson')}</Button>
        </div>
      </div>
      {financialQuery.isPending && <p className="reports-status">{t('common.loading')}</p>}
      {financialQuery.isError || financial?.available === false ? (
        <p className="reports-status reports-status--error">{t('reports.financial.unavailable')}</p>
      ) : financial && (
        <>
          <div className="reports-financial-grid">
            <div className="reports-metric">
              <span>{t('reports.financial.revenue')}</span>
              <strong>{formatAmount(financial.revenue?.amount)} {financial.currency}</strong>
            </div>
            <div className="reports-metric">
              <span>{t('reports.financial.grossProfit')}</span>
              <strong>{formatAmount(financial.gross_profit?.amount)} {financial.gross_profit?.amount !== null ? financial.currency : ''}</strong>
            </div>
            <div className="reports-metric">
              <span>{t('reports.financial.grossMargin')}</span>
              <strong>{financial.gross_margin_pct?.recent === null || financial.gross_margin_pct?.recent === undefined ? t('reports.common.unknown') : `${currencyFormatter.format(financial.gross_margin_pct.recent)}%`}</strong>
            </div>
            <div className="reports-metric">
              <span>{t('reports.financial.costCoverage')}</span>
              <strong>{financial.cost_data_coverage_pct === null || financial.cost_data_coverage_pct === undefined ? t('reports.common.unknown') : `${currencyFormatter.format(financial.cost_data_coverage_pct)}%`}</strong>
            </div>
          </div>
          <p className="reports-financial-note">{t('reports.financial.grossProfitNote')}</p>
        </>
      )}
    </Card>

    <Card className="reports-section">
      <div className="reports-section__header">
        <h2>{t('reports.sales.title')}</h2>
        <div className="reports-section__actions">
          <label htmlFor="reports-start-date">{t('reports.sales.startDate')}</label>
          <input id="reports-start-date" type="date" value={startDate} onChange={(event) => { setStartDate(event.target.value); setPage(0); }} className="reports-date-input" />
          <label htmlFor="reports-end-date">{t('reports.sales.endDate')}</label>
          <input id="reports-end-date" type="date" value={endDate} onChange={(event) => { setEndDate(event.target.value); setPage(0); }} className="reports-date-input" />
          <Button size="sm" variant="outline" leadingIcon={<Download size={14} />} disabled={!totalRows || Boolean(exporting)} onClick={() => exportSales('csv')}>{exporting === 'csv' ? t('reports.sales.exporting') : t('reports.common.exportCsv')}</Button>
          <Button size="sm" variant="outline" leadingIcon={<Download size={14} />} disabled={!totalRows || Boolean(exporting)} onClick={() => exportSales('json')}>{exporting === 'json' ? t('reports.sales.exporting') : t('reports.common.exportJson')}</Button>
          <Button size="sm" variant="outline" leadingIcon={<FileText size={14} />} disabled={!totalRows || Boolean(exporting)} onClick={() => exportSales('pdf')}>{exporting === 'pdf' ? t('reports.sales.exporting') : t('reports.common.exportPdf')}</Button>
        </div>
      </div>
      {exportFailed && <p className="reports-status reports-status--error" role="alert">{t('reports.sales.exportFailed')}</p>}
      {salesQuery.isPending && <p className="reports-status">{t('common.loading')}</p>}
      {salesQuery.isError || sales?.available === false ? (
        <p className="reports-status reports-status--error">{t('reports.sales.unavailable')}</p>
      ) : sales && sales.rows.length === 0 ? (
        <p className="reports-status">{t('reports.sales.empty')}</p>
      ) : sales && (
        <>
          <Table columns={tableColumns} data={tableRows} ariaLabel={t('reports.sales.title')} />
          {pageCount > 1 && (
            <nav className="reports-pagination" aria-label={t('reports.sales.pagination')}>
              <span>{t('reports.sales.pageOf', { from: firstRow, to: firstRow + tableRows.length - 1, total: totalRows })}</span>
              <Button size="sm" variant="outline" disabled={page === 0 || salesQuery.isFetching} onClick={() => setPage(page - 1)}>{t('reports.sales.previous')}</Button>
              <Button size="sm" variant="outline" disabled={page >= pageCount - 1 || salesQuery.isFetching} onClick={() => setPage(page + 1)}>{t('reports.sales.next')}</Button>
            </nav>
          )}
        </>
      )}
    </Card>
  </div>;
}
