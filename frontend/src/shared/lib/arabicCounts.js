// Arabic counted nouns agree with the number: 1 يوم واحد, 2 يومان, 3-10 أيام,
// 11-99 يومًا, 0 and 100+ يوم. The Arabic messages are written with the
// 11-99 form ("{{days}} يومًا"), so a count of 7 read "7 يومًا". This fixes
// the noun after a whole number using the CLDR Arabic plural rules.
const ARABIC_COUNTED_NOUNS = {
  'يومًا': { zero: '{n} يوم', one: 'يوم واحد', two: 'يومان', few: '{n} أيام', many: '{n} يومًا', other: '{n} يوم' },
  'طلبًا': { zero: '{n} طلب', one: 'طلب واحد', two: 'طلبان', few: '{n} طلبات', many: '{n} طلبًا', other: '{n} طلب' },
  'منتج': { zero: '{n} منتج', one: 'منتج واحد', two: 'منتجان', few: '{n} منتجات', many: '{n} منتجًا', other: '{n} منتج' },
};
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
let arabicPluralRules;

export function agreeArabicCounts(text) {
  return String(text).replace(
    /(?<![0-9٠-٩.,٫٬])([0-9٠-٩][0-9٠-٩,٬]*)(\s+)(يومًا|طلبًا|منتج)(?![\u0600-\u06FF])/g,
    (match, number, space, noun) => {
      const value = Number(number.replace(/[,٬]/g, '').replace(/[٠-٩]/g, (d) => ARABIC_DIGITS.indexOf(d)));
      if (!Number.isInteger(value)) return match;
      arabicPluralRules ??= new Intl.PluralRules('ar');
      return ARABIC_COUNTED_NOUNS[noun][arabicPluralRules.select(value)].replace('{n}', number);
    },
  );
}
