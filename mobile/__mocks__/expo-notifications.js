// Мок expo-notifications для jest (3.4): нативного модуля в тестах нет.
let permission = 'undetermined';
const listeners = [];
module.exports = {
  __setPermission: (status) => { permission = status; },
  __tap: (data) => listeners.forEach((fn) => fn({ notification: { request: { content: { data } } } })),
  getPermissionsAsync: jest.fn(async () => ({ status: permission })),
  requestPermissionsAsync: jest.fn(async () => ({ status: permission === 'undetermined' ? 'granted' : permission })),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[test-device]' })),
  addNotificationResponseReceivedListener: jest.fn((fn) => {
    listeners.push(fn);
    return { remove: () => listeners.splice(listeners.indexOf(fn), 1) };
  }),
  setNotificationHandler: jest.fn(),
};
