CEOPRO Data Connection upload fixtures

All four files are synthetic, fictional business records formatted to match the supplied CEOPRO template. They are test data, not real company financial records.

Each file is exactly 10,000,000 bytes (10 MB decimal). This is below the backend's 10 MiB limit (10,485,760 bytes).

Files:
- Cedar_Sage_Business_Data_10MB.csv — 60,586 business rows plus the header; size comes from CSV rows.
- Cedar_Sage_Business_Data_10MB.xlsx — 1,500 business rows; includes an unreferenced ZIP member to bring the upload size to 10 MB.
- Cedar_Sage_Business_Data_10MB.xlsm — same template data and structure as the XLSX fixture, with no VBA macros; includes an unreferenced ZIP member for size testing.
- Cedar_Sage_Business_Data_10MB.pdf — 300 business rows across 11 pages; includes PDF comments before EOF for upload-size testing.

The XLSX/XLSM ZIP member and PDF comments add file bytes but are not business rows and may be ignored by parsers. These fixtures test template acceptance and near-limit upload handling. AI extraction may truncate large row sets according to the AI service's own output limit. If your tenant has a 10,000 KB monthly document-extraction quota, it can accept only one of these 10 MB files before that quota is exhausted; reset or increase the test tenant quota before uploading another.
