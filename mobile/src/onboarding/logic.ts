// Правило возобновления (решения владельца 23.11.2026, 02:19 и 02:24): приложение свёрнуто или закрыто
// дольше порога (по умолчанию 5 минут, настройка сервера) — обучение начинается заново; меньше — с того же шага.
export type SavedTour = { index: number; leftAt: number | null };

export const TOUR_STORAGE_KEY = 'satti-onboarding-v1';

export function resumeIndex(saved: SavedTour | null, now: number, restartMinutes: number): number {
  if (!saved) return 0;
  if (saved.leftAt !== null && now - saved.leftAt > restartMinutes * 60_000) return 0;
  return Math.max(0, saved.index);
}

export function parseSaved(raw: string | null): SavedTour | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<SavedTour>;
    if (typeof v.index !== 'number') return null;
    return { index: v.index, leftAt: typeof v.leftAt === 'number' ? v.leftAt : null };
  } catch {
    return null;
  }
}
