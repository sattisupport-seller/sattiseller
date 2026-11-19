// Тексты локализации (docs/design.md, раздел 9). Казахские тексты требуют проверки носителем языка.

export type Locale = 'ru' | 'kk';

export const messages = {
  ru: {
    tabs: {
      overview: 'Обзор',
      orders: 'Заказы',
      products: 'Товары',
      assistant: 'Помощник',
      profile: 'Профиль',
    },
    placeholder: {
      soon: 'Экран появится в следующих задачах плана (docs/spec.md, раздел 16).',
    },
  },
  kk: {
    tabs: {
      overview: 'Шолу',
      orders: 'Тапсырыстар',
      products: 'Тауарлар',
      assistant: 'Көмекші',
      profile: 'Профиль',
    },
    placeholder: {
      soon: 'Бұл экран жоспардың келесі тапсырмаларында пайда болады.',
    },
  },
} as const;

export type Messages = (typeof messages)['ru'];

// Язык по умолчанию — русский (docs/design.md, раздел 2).
export const t: Messages = messages.ru;
