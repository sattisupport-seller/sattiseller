// Обучение после регистрации (К-21, часть 2, п.6): обязательное, без «Пропустить»; до конца обучения подключение
// Kaspi недоступно (и в приложении, и на сервере). Свернул или закрыл приложение дольше порога — заново (logic.ts).
// «Обучение пройдено» хранится у аккаунта на сервере: на втором устройстве не повторяется. Пройти ещё раз — из профиля.
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState, useWindowDimensions, View } from 'react-native';

import { request } from '@/api/client';
import { useAppConfig, useMe } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { deleteItem, getItem, setItem } from '@/lib/storage';
import { useSession } from '@/session/SessionProvider';
import { useTheme } from '@/theme/useTheme';

import { TOUR_STORAGE_KEY, parseSaved, resumeIndex } from './logic';
import { TOUR_STEPS, type TourArea } from './steps';

type TourValue = {
  active: boolean;
  index: number;
  done: boolean;  // пройдено (сервер) — Kaspi можно подключать
  start: () => void;  // пройти ещё раз из профиля
};

const Ctx = createContext<TourValue>({ active: false, index: 0, done: true, start: () => undefined });

export function useTour(): TourValue {
  return useContext(Ctx);
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { status, isDemo, termsRequired } = useSession();
  const signedIn = status === 'ready' && !isDemo;
  const me = useMe(signedIn);
  const config = useAppConfig();
  const qc = useQueryClient();
  const router = useRouter();
  const restartMinutes = config.data?.onboarding_restart_minutes ?? 5;
  const [active, setActive] = useState(false);
  const [index, setIndex] = useState(0);
  const indexRef = useRef(0);
  const finishedRef = useRef(false);  // пройдено в этой сессии: не запускать снова, пока /me не обновился
  const serverDone = me.data?.onboarding_done === true;

  const go = useCallback((i: number) => {
    indexRef.current = i;
    setIndex(i);
    void setItem(TOUR_STORAGE_KEY, JSON.stringify({ index: i, leftAt: null }));
    router.push(TOUR_STEPS[i].route as never);
  }, [router]);

  // запуск: после регистрации, пока на сервере нет отметки
  useEffect(() => {
    if (!signedIn || termsRequired || !me.data || serverDone || active || finishedRef.current) return;
    let alive = true;
    (async () => {
      const saved = parseSaved(await getItem(TOUR_STORAGE_KEY));
      if (!alive) return;
      setActive(true);
      go(resumeIndex(saved, Date.now(), restartMinutes));
    })();
    return () => { alive = false; };
  }, [signedIn, termsRequired, me.data, serverDone, active, restartMinutes, go]);

  // свернул — запоминаем время; вернулся — тот же шаг или заново
  useEffect(() => {
    if (!active) return;
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'background' || state === 'inactive') {
        void setItem(TOUR_STORAGE_KEY, JSON.stringify({ index: indexRef.current, leftAt: Date.now() }));
      } else if (state === 'active') {
        void (async () => {
          const saved = parseSaved(await getItem(TOUR_STORAGE_KEY));
          go(resumeIndex(saved, Date.now(), restartMinutes));
        })();
      }
    });
    return () => sub.remove();
  }, [active, restartMinutes, go]);

  const next = useCallback(async () => {
    if (indexRef.current < TOUR_STEPS.length - 1) {
      go(indexRef.current + 1);
      return;
    }
    finishedRef.current = true;
    setActive(false);
    await deleteItem(TOUR_STORAGE_KEY);
    try {
      await request('/me/onboarding/complete', { method: 'POST' });
    } finally {
      await qc.invalidateQueries({ queryKey: ['me'] });
      router.push('/settings/kaspi' as never);
    }
  }, [go, qc, router]);

  const start = useCallback(() => {
    setActive(true);
    go(0);
  }, [go]);

  const value = useMemo(() => ({ active, index, done: !signedIn || serverDone, start }), [active, index, signedIn, serverDone, start]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {active ? <TourOverlay index={index} onNext={() => { void next(); }} /> : null}
    </Ctx.Provider>
  );
}

function areaRect(area: TourArea, height: number): { top: number; height: number } {
  if (area === 'top') return { top: height * 0.08, height: height * 0.3 };
  if (area === 'middle') return { top: height * 0.35, height: height * 0.3 };
  if (area === 'bottom') return { top: height * 0.72, height: height * 0.14 };
  return { top: height - 84, height: 84 };  // панель вкладок
}

// Затемнение с «окном» над нужной частью экрана и карточка шага. Без «Пропустить» — только «Далее».
export function TourOverlay({ index, onNext }: { index: number; onNext: () => void }) {
  const { colors, spacing, radii } = useTheme();
  const { height } = useWindowDimensions();
  const step = TOUR_STEPS[index];
  const hole = areaRect(step.area, height);
  const dim = 'rgba(0,0,0,0.55)';
  const cardOnTop = hole.top > height / 2;
  const last = index === TOUR_STEPS.length - 1;
  return (
    <View style={{ position: 'absolute', left: 0, right: 0, top: 0, bottom: 0 }} accessibilityViewIsModal>
      <View style={{ height: hole.top, backgroundColor: dim }} />
      <View style={{ height: hole.height, borderWidth: 3, borderColor: colors.primary, borderRadius: radii.md }} />
      <View style={{ flex: 1, backgroundColor: dim }} />
      <Card style={{ position: 'absolute', left: spacing.lg, right: spacing.lg, gap: spacing.sm,
        ...(cardOnTop ? { top: spacing['2xl'] } : { bottom: spacing['2xl'] }) }}>
        <Txt variant="footnote" tone="secondary">{`Шаг ${index + 1} из ${TOUR_STEPS.length}`}</Txt>
        <Txt variant="headline" accessibilityRole="header">{step.title}</Txt>
        <Txt variant="body">{step.text}</Txt>
        <Button title={last ? 'Готово' : 'Далее'} onPress={onNext} fullWidth />
      </Card>
    </View>
  );
}
