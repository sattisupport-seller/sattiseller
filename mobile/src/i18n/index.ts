import { useCallback } from 'react';

import { useSession } from '@/session/SessionProvider';

import { kk } from './kk';
import { ru, type Dict } from './ru';

export type Locale = 'ru' | 'kk';

const dictionaries: Record<Locale, Dict> = { ru, kk };

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
