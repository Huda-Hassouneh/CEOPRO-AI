// Terms of Service and Privacy Policy, in English and Arabic.
// The wording describes what KEEL actually does with data (see the backend:
// tenant isolation, AI providers, payment processing, competitor research
// from public sources). Keep it in step with the product when that changes.
export const LEGAL_LAST_UPDATED = '2026-10-08';

export const legalContent = {
  terms: {
    en: {
      title: 'Terms of Service',
      intro: 'These terms govern your company’s use of KEEL, a business-intelligence service for sales, demand, pricing, competitors and marketing. By creating an account you agree to them on behalf of your company.',
      sections: [
        ['Your account', 'You are responsible for the people you invite, for keeping passwords private and for the activity on your company’s workspace. Each workspace belongs to one company; its data is kept separate from every other company’s.'],
        ['Your data', 'Your company keeps ownership of everything it uploads or connects: products, sales, documents, competitor notes and settings. We process it only to provide the service to you. You may export or delete it at any time; deleting your workspace removes its data from our active systems.'],
        ['Market and competitor research', 'KEEL collects publicly available information (public web pages, business listings, published prices and reviews) to build your competitor and market views. It respects website rules for automated access, records where each item came from, and never presents an estimate as a verified fact. You are responsible for how you use competitor information.'],
        ['AI features', 'Forecasts, recommendations, assistant answers and marketing content are generated from your data and may contain mistakes. Review them before acting, especially for pricing, stock and published content. Every answer shows where its information came from.'],
        ['Plans, billing and trials', 'Paid plans are billed in advance through our payment processor for the period you choose and renew automatically until cancelled. You can cancel from Billing; access continues until the end of the paid period. Plan limits (for example assistant questions or tracked competitors) are shown in Billing.'],
        ['Acceptable use', 'Do not use KEEL to break the law, infringe others’ rights, collect personal data about individuals, overload or attack the service, or try to access another company’s data.'],
        ['Availability and changes', 'We work to keep KEEL available and secure but cannot guarantee uninterrupted service. We may improve or change features; material changes to these terms will be announced in the app before they apply.'],
        ['Liability', 'To the extent allowed by law, KEEL is provided “as is” and our total liability is limited to the fees your company paid in the twelve months before the claim.'],
      ],
    },
    ar: {
      title: 'شروط الخدمة',
      intro: 'تنظم هذه الشروط استخدام شركتك لـ KEEL، وهي خدمة لذكاء الأعمال تغطي المبيعات والطلب والتسعير والمنافسين والتسويق. بإنشاء حساب فإنك توافق عليها نيابةً عن شركتك.',
      sections: [
        ['حسابك', 'أنت مسؤول عن الأشخاص الذين تدعوهم، وعن الحفاظ على سرية كلمات المرور، وعن النشاط في مساحة عمل شركتك. كل مساحة عمل تخص شركة واحدة، وتُحفظ بياناتها منفصلة عن بيانات أي شركة أخرى.'],
        ['بياناتك', 'تحتفظ شركتك بملكية كل ما ترفعه أو تربطه: المنتجات والمبيعات والمستندات وملاحظات المنافسين والإعدادات. نعالجها فقط لتقديم الخدمة لك. يمكنك تصديرها أو حذفها في أي وقت، وحذف مساحة العمل يزيل بياناتها من أنظمتنا العاملة.'],
        ['أبحاث السوق والمنافسين', 'يجمع KEEL معلومات متاحة للعامة (صفحات ويب عامة، وأدلة أعمال، وأسعار وتقييمات منشورة) لبناء صورة عن منافسيك وسوقك. يحترم قواعد المواقع للوصول الآلي، ويسجل مصدر كل معلومة، ولا يقدم تقديرًا على أنه حقيقة مؤكدة. أنت مسؤول عن طريقة استخدامك لمعلومات المنافسين.'],
        ['ميزات الذكاء الاصطناعي', 'التوقعات والتوصيات وإجابات المساعد والمحتوى التسويقي تُنتج من بياناتك وقد تحتوي على أخطاء. راجعها قبل اتخاذ قرار، خاصةً في التسعير والمخزون والمحتوى المنشور. كل إجابة توضح مصدر معلوماتها.'],
        ['الخطط والفوترة والتجربة', 'تُدفع الخطط المدفوعة مقدمًا عبر معالج الدفع للفترة التي تختارها وتتجدد تلقائيًا حتى الإلغاء. يمكنك الإلغاء من صفحة الفوترة، ويستمر الوصول حتى نهاية الفترة المدفوعة. حدود الخطة (مثل أسئلة المساعد أو عدد المنافسين المتابعين) معروضة في صفحة الفوترة.'],
        ['الاستخدام المقبول', 'لا تستخدم KEEL لمخالفة القانون أو التعدي على حقوق الآخرين أو جمع بيانات شخصية عن أفراد أو إرهاق الخدمة أو مهاجمتها أو محاولة الوصول إلى بيانات شركة أخرى.'],
        ['التوفر والتغييرات', 'نعمل على إبقاء KEEL متاحًا وآمنًا لكن لا يمكننا ضمان عدم انقطاع الخدمة. قد نطور الميزات أو نغيرها، وسيتم الإعلان داخل التطبيق عن أي تغيير جوهري على هذه الشروط قبل تطبيقه.'],
        ['المسؤولية', 'في الحدود التي يسمح بها القانون، يُقدَّم KEEL «كما هو» وتقتصر مسؤوليتنا الإجمالية على الرسوم التي دفعتها شركتك خلال الاثني عشر شهرًا السابقة للمطالبة.'],
      ],
    },
  },
  privacy: {
    en: {
      title: 'Privacy Policy',
      intro: 'This policy explains what information KEEL handles, why, and the choices you have.',
      sections: [
        ['What we store', 'Account details (name, email, hashed password, language), your company profile, and the business data you add: products, sales, stock, documents, competitors, campaigns and settings. We also keep security and usage records (sign-ins, plan usage) to run and protect the service.'],
        ['How it is kept separate', 'Every record belongs to one company workspace. The database itself enforces that a workspace can only read its own rows, and uploaded files are stored under your workspace only.'],
        ['Service providers', 'We use a small set of providers only to run features you use: an AI language-model provider to write assistant answers and marketing copy (it receives the question and the relevant facts from your workspace, not your whole database); a payment processor to handle card payments (card details go directly to it and never touch our servers); and hosting and storage providers. Competitor research sends search terms built from your industry and product names to search and listing services; it does not send your sales or customer data.'],
        ['Public information about other businesses', 'Competitor features use information that businesses publish publicly. We keep the source of each item and do not collect personal data about individuals.'],
        ['Cookies and local storage', 'We use your browser’s storage to keep you signed in and remember your language and theme. We do not use advertising trackers.'],
        ['Retention and deletion', 'Data stays while your workspace is active. When a workspace is deleted, its data is removed from active systems; backups expire on their normal cycle. You can ask us to export or delete your data at any time.'],
        ['Security', 'Passwords are stored as one-way hashes, connections are encrypted, and access between companies is blocked at the database level.'],
        ['Your rights and contact', 'You can access, correct, export or delete your information from the app or by contacting us. We will tell you in the app before changing this policy in a way that affects you.'],
      ],
    },
    ar: {
      title: 'سياسة الخصوصية',
      intro: 'توضح هذه السياسة المعلومات التي يتعامل معها KEEL وسبب ذلك والخيارات المتاحة لك.',
      sections: [
        ['ما الذي نخزنه', 'بيانات الحساب (الاسم والبريد الإلكتروني وكلمة المرور المشفرة واللغة)، وملف شركتك، وبيانات الأعمال التي تضيفها: المنتجات والمبيعات والمخزون والمستندات والمنافسون والحملات والإعدادات. ونحتفظ أيضًا بسجلات الأمان والاستخدام (عمليات الدخول واستهلاك الخطة) لتشغيل الخدمة وحمايتها.'],
        ['كيف تبقى البيانات منفصلة', 'كل سجل يخص مساحة عمل شركة واحدة. قاعدة البيانات نفسها تفرض أن مساحة العمل لا تقرأ إلا سجلاتها، والملفات المرفوعة تُخزَّن ضمن مساحة عملك فقط.'],
        ['مزودو الخدمة', 'نستخدم عددًا محدودًا من المزودين لتشغيل الميزات التي تستخدمها فقط: مزود نماذج لغوية لكتابة إجابات المساعد والنصوص التسويقية (يتلقى السؤال والمعلومات ذات الصلة من مساحة عملك، لا قاعدة بياناتك كاملة)؛ ومعالج دفع للبطاقات (تذهب بيانات البطاقة إليه مباشرة ولا تمر بخوادمنا)؛ ومزودي الاستضافة والتخزين. أبحاث المنافسين ترسل كلمات بحث مبنية على قطاعك وأسماء منتجاتك إلى خدمات البحث والأدلة، ولا ترسل بيانات مبيعاتك أو عملائك.'],
        ['المعلومات العامة عن الشركات الأخرى', 'تستخدم ميزات المنافسين معلومات تنشرها الشركات للعامة. نحتفظ بمصدر كل معلومة ولا نجمع بيانات شخصية عن الأفراد.'],
        ['ملفات تعريف الارتباط والتخزين المحلي', 'نستخدم تخزين المتصفح لإبقائك مسجلًا للدخول وتذكر لغتك ومظهر الواجهة. لا نستخدم أدوات تتبع إعلانية.'],
        ['الاحتفاظ والحذف', 'تبقى البيانات ما دامت مساحة العمل نشطة. عند حذف مساحة العمل تُزال بياناتها من الأنظمة العاملة، وتنتهي النسخ الاحتياطية وفق دورتها المعتادة. يمكنك طلب تصدير بياناتك أو حذفها في أي وقت.'],
        ['الأمان', 'تُخزَّن كلمات المرور بتشفير أحادي الاتجاه، والاتصالات مشفرة، والوصول بين الشركات ممنوع على مستوى قاعدة البيانات.'],
        ['حقوقك والتواصل', 'يمكنك الاطلاع على معلوماتك وتصحيحها وتصديرها وحذفها من التطبيق أو بالتواصل معنا. سنبلغك داخل التطبيق قبل أي تغيير على هذه السياسة يؤثر عليك.'],
      ],
    },
  },
};
