import { Font, StyleSheet } from "@react-pdf/renderer";
import regularFont from "./fonts/DejaVuSans.ttf";
import boldFont from "./fonts/DejaVuSans-Bold.ttf";

Font.register({
  family: "MarketReport",
  fonts: [
    { src: regularFont, fontWeight: 400 },
    { src: boldFont, fontWeight: 700 }
  ]
});
Font.registerHyphenationCallback((word) => [word]);

export const pdfStyles = StyleSheet.create({
  page: {
    paddingTop: 38,
    paddingBottom: 48,
    paddingHorizontal: 34,
    fontFamily: "MarketReport",
    fontSize: 8.5,
    color: "#233049",
    backgroundColor: "#FFFFFF"
  },
  brand: { color: "#146C81", fontSize: 10, fontWeight: 700, letterSpacing: 1.2 },
  header: { borderBottomWidth: 1, borderBottomColor: "#D9E5EA", paddingBottom: 18, marginBottom: 20 },
  title: { fontSize: 20, fontWeight: 700, color: "#123044", marginTop: 9, marginBottom: 6 },
  subtitle: { fontSize: 9, color: "#587084", lineHeight: 1.5 },
  metadata: { flexDirection: "row", flexWrap: "wrap", marginTop: 15, gap: 14 },
  metadataItem: { paddingVertical: 6, paddingHorizontal: 9, backgroundColor: "#F2F7F9", borderRadius: 4 },
  metadataLabel: { fontSize: 7, color: "#64798A", marginBottom: 3 },
  metadataValue: { fontWeight: 700, fontSize: 8.5 },
  sectionHeading: { fontSize: 11, fontWeight: 700, color: "#123044", marginBottom: 10 },
  table: { borderWidth: 1, borderColor: "#DBE5EA", borderRadius: 4, overflow: "hidden" },
  tableHeader: { flexDirection: "row", backgroundColor: "#EAF2F5", borderBottomWidth: 1, borderBottomColor: "#D3E0E6" },
  tableRow: { flexDirection: "row", borderBottomWidth: 0.5, borderBottomColor: "#E6ECEF" },
  tableCell: { paddingHorizontal: 7, paddingVertical: 9, fontSize: 7.5, lineHeight: 1.4 },
  tableHeaderCell: { fontWeight: 700, color: "#294559", fontSize: 7 },
  tableDetail: { paddingHorizontal: 8, paddingVertical: 8, backgroundColor: "#F7FAFB", borderBottomWidth: 0.5, borderBottomColor: "#E6ECEF", fontSize: 7.5, lineHeight: 1.5 },
  detailLabel: { fontWeight: 700, color: "#426276" },
  empty: { padding: 18, backgroundColor: "#F2F7F9", color: "#587084", borderRadius: 4 },
  opportunity: { padding: 13, borderWidth: 1, borderColor: "#DBE5EA", borderRadius: 5, marginBottom: 10 },
  opportunityTop: { flexDirection: "row", justifyContent: "space-between", gap: 12, marginBottom: 8 },
  opportunityName: { fontSize: 10, fontWeight: 700, color: "#123044", flexGrow: 1 },
  opportunityGrowth: { fontSize: 11, fontWeight: 700, color: "#147B69" },
  opportunityExplanation: { lineHeight: 1.55, color: "#3B5061", marginBottom: 8 },
  status: { fontSize: 7, color: "#667F8E" },
  footer: {
    position: "absolute", bottom: 22, left: 34, right: 34,
    flexDirection: "row", justifyContent: "space-between", borderTopWidth: 1,
    borderTopColor: "#DFE8EC", paddingTop: 7, fontSize: 7, color: "#718596"
  }
});
