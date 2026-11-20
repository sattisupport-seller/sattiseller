import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

import { requestFile } from '@/api/client';

// Скачивание выгрузки с сервера во временную папку и системное меню «Поделиться» (ТЗ 2.1, 9.4–9.5).
// Файл только во временной папке: сервер его не хранит, телефон удаляет при очистке кэша.
export async function downloadAndShare(path: string, fileName: string, mimeType: string): Promise<void> {
  const bytes = await requestFile(path);
  const target = new File(Paths.cache, fileName);
  if (target.exists) target.delete();
  target.create();
  await target.write(new Uint8Array(bytes));
  if (!(await Sharing.isAvailableAsync())) throw new Error('sharing-unavailable');
  await Sharing.shareAsync(target.uri, { mimeType, dialogTitle: fileName });
}
