// Apple DeviceCheck (К-21): одноразовый токен устройства для правила «пробный период — один на телефон».
// Токен не содержит идентификатора телефона; сервер по нему читает и ставит два бита у Apple.
// В Expo Go и на симуляторе модуля или поддержки нет — возвращается null.
import { requireOptionalNativeModule } from 'expo-modules-core';

type Native = { isSupported(): boolean; generateTokenAsync(): Promise<string> };

const native = requireOptionalNativeModule<Native>('SattiDeviceCheck');

export async function generateTokenAsync(): Promise<string | null> {
  if (!native || !native.isSupported()) return null;
  try {
    return await native.generateTokenAsync();
  } catch {
    return null;
  }
}
