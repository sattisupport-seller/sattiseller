// Тексты ошибок черновиков ИИ (К-12, 22.11): пользователь видит понятную фразу, а не код и не «HTTP 403».
import { ApiError, reportClientError } from '@/api/client';
import type { useI18n } from '@/i18n';

type T = ReturnType<typeof useI18n>['t'];

export function draftErrorText(e: unknown, t: T): string {
  if (e instanceof ApiError) {
    if (e.code === 'ai_limit') return t('assistant.errLimit');
    if (e.code === 'ai_budget_exhausted') return t('assistant.errBudget');
    if (e.code === 'ai_disabled') return t('assistant.errDisabled');
    // 422 с текстом от сервера уже написан по-русски и говорит, что исправить (например, формат фото)
    if (e.code === 'validation' && e.message) return e.message;
    // К-24: условия (с согласием на ИИ) не приняты, аккаунт заблокирован или деактивирован — текст сервера
    if (e.status === 403 && e.message) return e.message;
    // К-35: нет связи — так и говорим, а не «попробуйте ещё раз»
    if (e.code === 'network') return t('assistant.errNetwork');
    if (e.status === 413) return t('assistant.errTooLarge');
    if (e.status >= 500) return t('assistant.errServer');
    return t('assistant.errGeneric');
  }
  // К-35: сбой на телефоне до отправки (подготовка фото или файла) — причину отправляем в журнал ошибок сервера
  reportClientError('ai-draft', e instanceof Error ? `${e.name}: ${e.message}` : String(e));
  return t('assistant.errLocal');
}
