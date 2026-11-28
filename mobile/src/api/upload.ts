import { File } from 'expo-file-system';

/**
 * К-35: файл для FormData (фото карточки, импорт затрат, прайс Kaspi, выгрузка Kaspi Pay).
 *
 * Причина ошибки «Не удалось составить черновик» на iPhone (Expo Go, SDK 58): глобальный `fetch` в Expo — это
 * `expo/fetch`, а он не поддерживает часть формы в виде React Native `{ uri, name, type }` и бросает
 * «Unsupported FormDataPart implementation» ещё до отправки — запрос до сервера не доходил.
 * `expo/fetch` принимает объект с `bytes()`: отдаём исходные имя и тип файла (сервер узнаёт .xlsx/.csv по имени),
 * а байты читаем из файла на телефоне.
 */
export function filePart(uri: string, name: string, type: string): Blob {
  try {
    const file = new File(uri);
    return { name, type, size: file.size, bytes: () => file.bytes() } as unknown as Blob;
  } catch {
    // без нативного модуля (тесты) — прежний вид части
    return { uri, name, type } as unknown as Blob;
  }
}
