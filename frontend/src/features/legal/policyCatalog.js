export const POLICY_CANDIDATE_VERSION = 'keel-public-candidate-2026-11-09.2';
export const POLICY_APPROVED = false;
export const POLICY_EFFECTIVE_DATE = null;
export const PUBLIC_POLICIES = [
  { kind: 'terms', path: '/terms', en: 'Terms of Service', ar: 'شروط الخدمة' },
  { kind: 'privacy', path: '/privacy', en: 'Privacy Policy', ar: 'سياسة الخصوصية' },
  { kind: 'refund', path: '/refund-policy', en: 'Refund Policy', ar: 'سياسة الاسترداد' },
  { kind: 'subscriptions', path: '/subscription-policy', en: 'Subscriptions and Cancellation', ar: 'الاشتراكات والإلغاء' },
  { kind: 'trial', path: '/trial-renewal', en: 'Free Trial and Automatic Renewal', ar: 'التجربة المجانية والتجديد التلقائي' },
  { kind: 'contact', path: '/contact', en: 'Contact and Support', ar: 'التواصل والدعم' },
];
export const policyCopy = {
  en: {
    navigation: 'Policies and support', language: 'العربية', draft: 'Draft for owner and legal review — not approved or effective.',
    notice: 'This local candidate does not authorize customer acceptance or payment activation. Unresolved fields require approval before publication.',
    linksNotice: 'Draft policy links for review only. Opening a page does not record acceptance or approve a plan change.',
    version: 'Proposed version', unresolved: 'Unresolved owner/legal decision', intentions: 'Previously approved commercial intentions',
    rules: [
      'B2B customers only. Eligible businesses may receive a 14-day trial requiring a payment method and explicit, initially unchecked recurring consent.',
      'The trial starts at the original provider’s authoritative confirmed trial-start timestamp. Checkout completion or a browser redirect alone is insufficient.',
      'Automatic paid renewal follows the exact disclosed, frozen plan amount, currency and billing interval after the applicable trial.',
      'Paid cancellation stops future renewals while retaining access through the paid entitlement period. Withdrawal before confirmation is separate from cancellation of an existing subscription.',
      'Refund requests may be reviewed within 14 days after the first paid charge. No refund is guaranteed; applicable law and the seller/provider’s obligations apply.',
      'Standard and eligible Custom Plans use their approved order or quote. No Custom price, paid overage, refund timing or additional rights are promised by this draft.',
    ],
    catalogTitle: 'Current authoritative catalog', catalogNote: 'Amounts and trial durations below come from the running backend catalog. This page does not set prices or establish provider readiness.',
    trialPolicy: 'Approved future offer: Standard, Plus and Pro each have a 14-day trial for eligible businesses. Existing subscriptions and local signup trials are unchanged. Provider-backed trials require a payment method and explicit recurring consent; the local signup trial is not proof of that setup.',
    discrepancy: 'Installed catalog differs from the approved 14-day Standard-plan policy. Apply the reviewed forward migration to the intended environment before offering new terms. Existing subscriptions and frozen orders must retain their original dates and terms.',
    periods: { monthly: 'Monthly', 'three-months': 'Every three months', 'six-months': 'Every six months', yearly: 'Yearly' },
    plan: 'Plan', period: 'Billing period', amount: 'Catalog amount', days: 'Trial days', unavailable: 'Catalog unavailable. No prices or trial durations have been substituted.',
    contactIntro: 'Owner-provided details proposed for public use; publication and legal approval remain pending.',
    operator: 'Huda Hassuneh (هدى حسونة), an individual in Jordan, operating KEEL.', email: 'Support, billing and privacy contact',
    missing: 'Address remains pending. No telephone number or business-registration claim has been supplied for publication.',
    provider: 'For an existing Paddle order, use the original receipt/portal or Paddle buyer support. KEEL does not promise to override the Merchant of Record’s refund or cancellation decisions.',
  },
  ar: {
    navigation: 'السياسات والدعم', language: 'English', draft: 'مسودة لمراجعة المالك والمراجعة القانونية — غير معتمدة وغير نافذة.',
    notice: 'لا تسمح هذه النسخة المحلية بقبول العملاء أو تفعيل الدفع. تتطلب الحقول غير المحسومة اعتماداً قبل النشر.',
    linksNotice: 'روابط مسودات للمراجعة فقط. فتح الصفحة لا يسجل موافقة ولا يعتمد تغيير الخطة.',
    version: 'النسخة المقترحة', unresolved: 'قرار غير محسوم للمالك أو المستشار القانوني', intentions: 'القرارات التجارية المعتمدة سابقاً',
    rules: [
      'الخدمة لعملاء الأعمال فقط. يمكن للأعمال المؤهلة الحصول على تجربة لمدة 14 يوماً تتطلب وسيلة دفع وموافقة صريحة على الدفع المتكرر عبر مربع غير محدد مسبقاً.',
      'تبدأ التجربة من وقت البداية الموثوق الذي يؤكده المزوّد الأصلي. اكتمال Checkout أو إعادة توجيه المتصفح وحدهما لا يكفيان.',
      'يبدأ التجديد المدفوع التلقائي بعد التجربة المطبقة وفق مبلغ الخطة وعملتها ودورتها المفصح عنها والمجمدة تحديداً.',
      'يوقف إلغاء الاشتراك المدفوع التجديدات المستقبلية مع استمرار الوصول حتى نهاية فترة الاستحقاق المدفوعة. سحب الموافقة قبل التأكيد يختلف عن إلغاء اشتراك قائم.',
      'يمكن مراجعة طلبات الاسترداد خلال 14 يوماً بعد أول دفعة مدفوعة. لا يوجد ضمان للاسترداد، وتسري القوانين والتزامات البائع أو المزوّد.',
      'تعتمد الخطط القياسية والمخصصة المؤهلة على الطلب أو العرض المعتمد. لا تعد هذه المسودة بسعر مخصص أو تجاوز مدفوع أو موعد استرداد أو حقوق إضافية.',
    ],
    catalogTitle: 'دليل الخطط المرجعي الحالي', catalogNote: 'تأتي المبالغ ومدد التجربة أدناه من دليل الخطط في الخادم. لا تحدد هذه الصفحة الأسعار ولا تثبت جاهزية المزوّد.',
    trialPolicy: 'العرض المستقبلي المعتمد: تجربة لمدة 14 يومًا للشركات المؤهلة في خطط Standard وPlus وPro. لا تتغير الاشتراكات القائمة أو تجارب التسجيل المحلية. تتطلب التجربة المرتبطة بالمزود وسيلة دفع وموافقة صريحة على الدفع المتكرر؛ تجربة التسجيل المحلية ليست إثباتًا لهذا الإعداد.',
    discrepancy: 'يختلف الكتالوج المثبت عن سياسة التجربة المعتمدة لمدة 14 يومًا للخطط القياسية. يجب تطبيق الترحيل الأمامي المراجع على البيئة المقصودة قبل تقديم الشروط الجديدة. تحتفظ الاشتراكات القائمة والطلبات المثبتة بتواريخها وشروطها الأصلية.',
    periods: { monthly: 'شهريًا', 'three-months': 'كل ثلاثة أشهر', 'six-months': 'كل ستة أشهر', yearly: 'سنويًا' },
    plan: 'الخطة', period: 'دورة الفوترة', amount: 'مبلغ الدليل', days: 'أيام التجربة', unavailable: 'دليل الخطط غير متاح. لم تُستبدل الأسعار أو مدد التجربة بقيم مفترضة.',
    contactIntro: 'تفاصيل قدمها المالك للاستخدام العام المقترح؛ ما زال النشر والاعتماد القانوني معلقين.',
    operator: 'هدى حسونة (Huda Hassuneh)، فرد في الأردن، تدير KEEL.', email: 'التواصل للدعم والفوترة والخصوصية',
    missing: 'العنوان ما زال معلقاً. لم يُقدم رقم هاتف أو ادعاء بتسجيل تجاري للنشر.',
    provider: 'لطلب Paddle قائم، استخدم الإيصال أو البوابة الأصلية أو دعم مشتري Paddle. لا تعد KEEL بتجاوز قرارات بائع السجل بشأن الاسترداد أو الإلغاء.',
  },
};

// Raw HTML is always text; this model has no executable markup.
export function parsePolicyMarkdown(text) {
  return text.split(/\n\s*\n/).map(value => value.trim()).filter(value => value && !value.startsWith('# ') && value !== '---').map(value => {
    if (value.startsWith('## ')) {
      const [heading, ...body] = value.split('\n');
      return { type: 'section', heading: heading.slice(3), body: body.join('\n') };
    }
    return { type: value.startsWith('- ') ? 'list' : value.startsWith('> ') ? 'note' : 'paragraph', body: value.replace(/^>\s?/gm, '') };
  });
}
