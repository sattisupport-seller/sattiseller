import { useCallback } from 'react';

import { useSession } from '@/session/SessionProvider';

import { ru, type Dict } from './ru';

// К-13 (22.11): только русский. kk.ts оставлен в репозитории, но не подключён.
export type Locale = 'ru';
/** Языки интерфейса, подключённые в приложение (К-13: только русский). */
export const LOCALES: readonly Locale[] = ['ru'];

const dictionaries: Record<Locale, Dict> = { ru };

// Пути вида "overview.title" — проверяются типами: опечатка в ключе не соберётся.
type Paths<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Paths<T[K], `${P}${K}.`>;
}[keyof T & string];

export type TKey = Paths<Dict>;

function lookup(dict: Dict, key: string): string {
  const parts = key.split('.');
  let node: unknown = dict;
  for (const part of parts) {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return key;
    }
  }
  return typeof node === 'string' ? node : key;
}

/** Подстановка {name} в тексте. */
export function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export function translate(locale: Locale, key: TKey, vars?: Record<string, string | number>): string {
  return interpolate(lookup(dictionaries[locale], key), vars);
}

export function useI18n() {
  const { locale } = useSession();
  const t = useCallback(
    (key: TKey, vars?: Record<string, string | number>) => translate(locale, key, vars),
    [locale],
  );
  return { t, locale };
}
