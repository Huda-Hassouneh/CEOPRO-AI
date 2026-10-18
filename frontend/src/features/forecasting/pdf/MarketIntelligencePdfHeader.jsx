import { Text, View } from "@react-pdf/renderer";
import { pdfStyles as s } from "./marketIntelligencePdfStyles.js";

export function MarketIntelligencePdfHeader({ title, subtitle, product, period, generated, labels, rtl }) {
  const metadata = [
    [labels.product, product],
    [labels.period, period],
    [labels.generated, generated]
  ];

  return (
    <View style={s.header}>
      <Text style={s.brand}>KEEL</Text>
      <Text style={[s.title, rtl && { textAlign: "right" }]}>{title}</Text>
      <Text style={[s.subtitle, rtl && { textAlign: "right" }]}>{subtitle}</Text>
      <View style={[s.metadata, rtl && { flexDirection: "row-reverse" }]}>
        {metadata.map(([label, value]) => (
          <View key={label} style={s.metadataItem}>
            <Text style={[s.metadataLabel, rtl && { textAlign: "right" }]}>{label}</Text>
            <Text style={[s.metadataValue, rtl && { textAlign: "right" }]}>{value}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}
