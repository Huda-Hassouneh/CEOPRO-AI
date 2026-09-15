const localized = (en, ar) => ({ en, ar });

export const connectDataMockData = Object.freeze({
  connectedSources: [
    {
      id: 'source-documents', type: 'documents', name: localized('Business Data Files', 'ملفات بيانات الأعمال'), status: 'connected',
      lastUpdatedAt: '2026-09-15T08:20:00Z', recordCount: 18420,
      categories: [localized('Sales', 'المبيعات'), localized('Products', 'المنتجات'), localized('Inventory', 'المخزون')],
      dataStatus: 'verified', actions: ['details', 'uploadVersion'],
    },
    {
      id: 'source-website', type: 'website', name: localized('Company Website', 'موقع الشركة'), status: 'processing',
      lastUpdatedAt: '2026-09-15T07:55:00Z', recordCount: null,
      categories: [localized('Products', 'المنتجات'), localized('Pricing', 'التسعير')],
      actions: ['details'],
    },
    {
      id: 'source-analytics', type: 'analytics', name: localized('Google Analytics', 'Google Analytics'), status: 'needsAttention',
      lastUpdatedAt: '2026-09-12T13:10:00Z', recordCount: 7310,
      categories: [localized('Website traffic', 'زيارات الموقع'), localized('Customer activity', 'نشاط العملاء')],
      actions: ['details', 'reconnect'],
    },
  ],
  recentImports: [
    { id: 'import-1', date: '2026-09-15T08:20:00Z', source: localized('Business Data Files', 'ملفات بيانات الأعمال'), name: 'quarterly-data.xlsx', type: 'xlsx', status: 'completed' },
    { id: 'import-2', date: '2026-09-15T07:55:00Z', source: localized('Company Website', 'موقع الشركة'), name: localized('Scheduled website scan', 'فحص الموقع المجدول'), type: 'connection', status: 'processing' },
    { id: 'import-3', date: '2026-09-13T11:30:00Z', source: localized('Business Data Files', 'ملفات بيانات الأعمال'), name: 'inventory-update.csv', type: 'csv', status: 'failed' },
  ],
  availableSourceTypes: ['analytics', 'website', 'businessSystem', 'documents'],
});
