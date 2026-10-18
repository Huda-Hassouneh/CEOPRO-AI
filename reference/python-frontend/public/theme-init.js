// Runs before first paint (loaded as a blocking script in <head>): applies the
// saved KEEL theme (light is the default) and turns on glass refraction where
// it renders - only Chromium renders SVG filters inside backdrop-filter.
// A file rather than an inline script so the Content-Security-Policy can
// allow same-origin scripts only.
try { if (navigator.userAgentData && navigator.userAgentData.brands.some(function (b) { return /Chromium/i.test(b.brand); })) document.documentElement.setAttribute('data-refract', ''); } catch (e) {}
try { if (localStorage.getItem('apex_theme') === 'dark') { document.documentElement.setAttribute('data-theme', 'dark'); document.querySelector('meta[name="theme-color"]').setAttribute('content', '#1b1d22'); } } catch (e) {}
