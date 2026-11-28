// К-35 п.5: экраны вкладок берут отступ сверху из безопасной зоны; в тестах — готовый мок библиотеки
jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
