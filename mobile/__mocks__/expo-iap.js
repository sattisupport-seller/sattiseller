// В тестах нативного модуля покупок нет — как в Expo Go: src/lib/purchases.ts видит «покупки недоступны».
// Тесты сценария покупки подменяют сам '@/lib/purchases' (src/__qa__/paywall-store.test.tsx).
throw new Error('expo-iap: native module is not available in tests');
