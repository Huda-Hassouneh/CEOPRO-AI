import { Text, View } from "@react-pdf/renderer";
import { pdfStyles as s } from "./marketIntelligencePdfStyles.js";

export function MarketIntelligencePdfTable({ columns, rows, emptyLabel, detail, rtl = false }) {
  if (!rows?.length) return <Text style={s.empty}>{emptyLabel}</Text>;

  return (
    <View style={s.table}>
      <View style={[s.tableHeader, rtl && { flexDirection: "row-reverse" }]}>
        {columns.map((column) => (
          <Text key={column.key} style={[s.tableCell, s.tableHeaderCell, { flex: column.width || 1 }, rtl && { textAlign: "right" }]}>
            {column.label}
          </Text>
        ))}
      </View>
      {rows.map((row, index) => (
        <View key={row.id ?? index} wrap={false}>
          <View style={[s.tableRow, rtl && { flexDirection: "row-reverse" }]}>
            {columns.map((column) => (
              <Text key={column.key} style={[s.tableCell, { flex: column.width || 1 }, rtl && { textAlign: "right" }]}>
                {String(column.value(row) ?? "—")}
              </Text>
            ))}
          </View>
          {detail && <View style={s.tableDetail}>{detail(row)}</View>}
        </View>
      ))}
    </View>
  );
}
