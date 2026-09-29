import { createElement } from "react";
import { pdf } from "@react-pdf/renderer";
import { MarketIntelligencePdfDocument } from "../pdf/MarketIntelligencePdfDocument.jsx";

export async function exportMarketIntelligencePdf({ data, section, locale, periodDays }) {
  if (!data?.selectedProduct) throw new Error("No Market Intelligence data is available for export.");

  const generatedAt = new Date();
  const blob = await pdf(createElement(MarketIntelligencePdfDocument, {
    data, section, locale, periodDays, generatedAt
  })).toBlob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `CEOPRO-Market-Intelligence-${section}-${generatedAt.toISOString().slice(0, 10)}.pdf`;

  try {
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    // The browser may still be reading the object URL after click() returns.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
