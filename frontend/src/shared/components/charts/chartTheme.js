import { useTheme } from '../../../app/providers/ThemeProvider.jsx';

// Series colours per theme, each pair validated against its own surface with
// the dataviz palette checker (light on #f8f9fc, dark on #1a2148). The forecast
// is also dashed, so actual vs forecast never relies on colour alone.
export const CHART_THEMES = {
  light: {
    actual: '#0d9488', forecast: '#6366f1', axis: '#5c6280', cursor: 'rgba(60,66,110,0.3)',
    reference: 'rgba(60,66,110,0.45)', label: '#151a2e', item: '#3b4160', dotRing: '#ffffff',
  },
  dark: {
    actual: '#12a594', forecast: '#7c80f2', axis: '#9ea6d4', cursor: 'rgba(200,210,255,0.35)',
    reference: 'rgba(200,210,255,0.45)', label: '#f2f4ff', item: '#c9cef0', dotRing: '#1a2148',
  },
};

// Charts draw in on load: one smooth ease, not a bounce.
export const CHART_ANIMATION = { isAnimationActive: true, animationDuration: 1100, animationEasing: 'ease-out' };

export function useChartTheme() {
  const { theme } = useTheme();
  return CHART_THEMES[theme] || CHART_THEMES.light;
}
