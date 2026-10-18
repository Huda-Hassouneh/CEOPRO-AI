export function calculatePlanPrice(
  itemPrice: number,
  discountValue: number,
  discountType: string
) {
  if (discountType == "percentage") {
    const finalPrice = (itemPrice - (itemPrice * discountValue) / 100).toFixed(
      2
    );
    return finalPrice;
  }

  if (discountType == "fixed_amount") {
    const finalPrice = (itemPrice - discountValue).toFixed(2);
    return finalPrice;
  }
}
